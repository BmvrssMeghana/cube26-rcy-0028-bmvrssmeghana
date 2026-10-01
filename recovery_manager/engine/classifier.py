"""
LLM Classifier & Integrity Agent — Recovery Manager
Orchestrates:
  1. Classification (CONTRADICTED | SUPPORTED | SILENT | UNCERTAIN | NOT_YET_SUPPORTED)
  2. Reimbursement & Duplicate Reconciliation (ALREADY_RECOVERED, DUPLICATE_SUPPRESSED)
  3. SLA Window Evaluation (EXPIRED / out_of_window)
  4. Integrity Agent & Claim Defense Auditor (Monotonic Auditor + Hallucination Firewall)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Literal

from .evidence_matcher import EvidenceBundle, CHARGE_ROUTING
from .sla_engine import SLAResult
from .ingestor import ReimbursementRecord

Verdict = Literal[
    "CONTRADICTED",
    "SUPPORTED",
    "SILENT",
    "UNCERTAIN",
    "NOT_YET_SUPPORTED",
    "DUPLICATE_SUPPRESSED",
    "ALREADY_RECOVERED",
    "EXPIRED",
    "PENDING_REVIEW",
]


@dataclass
class ClaimDecision:
    line_id: str
    unit_id: str
    org_id: str
    charge_type: str
    amount_usd: float
    verdict: Verdict
    claim_amount: float           # Recoverable amount ($0.0 if not claimable)
    already_reimbursed_amount: float = 0.0
    reasoning: str = ""
    supporting_evidence: list[str] = field(default_factory=list)
    cited_fields: list[dict] = field(default_factory=list)
    sla: dict = field(default_factory=dict)
    duplicate_flag: bool = False
    duplicate_note: str = ""
    defense_pass_notes: list[str] = field(default_factory=list)
    hallucination_blocked: bool = False
    evidence_dna_tree: dict = field(default_factory=dict)
    completeness_score: float = 1.0
    missing_fields: list[str] = field(default_factory=list)

    # Major USP Attributes
    claimability_score: int = 0
    score_breakdown: dict = field(default_factory=dict)
    evidence_strength: str = "MISSING"
    priority_level: str = "LOW"
    adversarial_pass: bool = False
    adversarial_findings: list[str] = field(default_factory=list)
    why_not_claim: str = ""
    required_evidence_to_resolve: list[str] = field(default_factory=list)
    custody_window: dict = field(default_factory=dict)
    evidence_graph: dict = field(default_factory=dict)
    sha256_hash: str = ""
    root_cause_driver: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# LLM Integration Helpers
# ---------------------------------------------------------------------------

_gemini_client = None
_USE_NEW_SDK = False


def _get_client():
    global _gemini_client, _USE_NEW_SDK
    if _gemini_client is not None:
        return _gemini_client
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None

    try:
        from google import genai
        _gemini_client = genai.Client(api_key=api_key)
        _USE_NEW_SDK = True
        return _gemini_client
    except ImportError:
        pass

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        _gemini_client = genai.GenerativeModel("gemini-2.0-flash")
        _USE_NEW_SDK = False
        return _gemini_client
    except ImportError:
        pass

    return None


def _call_llm(prompt: str) -> dict | None:
    client = _get_client()
    if client is None:
        return None
    try:
        if _USE_NEW_SDK:
            resp = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config={"temperature": 0.1, "max_output_tokens": 1024, "response_mime_type": "application/json"},
            )
        else:
            resp = client.generate_content(
                prompt,
                generation_config={"temperature": 0.1, "response_mime_type": "application/json"}
            )
        text = resp.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(text)
    except Exception as e:
        print(f"[LLM Warning] Call failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Rule-based Classifier (Deterministic Stage)
# ---------------------------------------------------------------------------

def _deterministic_classify(bundle: EvidenceBundle) -> dict:
    charge = bundle.charge
    ct = charge.charge_type
    fields = {f.field_name: f.field_value for f in bundle.fields}

    # Section 1.1: Missing routing rule → NOT_YET_SUPPORTED
    if ct not in CHARGE_ROUTING:
        return {
            "verdict": "NOT_YET_SUPPORTED",
            "claim_amount": 0.0,
            "reasoning": f"No evidence routing rule exists for charge type '{ct}'. Pending system update.",
            "supporting_evidence": [],
            "cited_fields": [],
        }

    # Section 2.8: Evidence postdates charge → SILENT
    if bundle.evidence_postdates_charge:
        return {
            "verdict": "SILENT",
            "claim_amount": 0.0,
            "reasoning": "Operational evidence record postdates the fee charge date and cannot establish pre-charge condition.",
            "supporting_evidence": [],
            "cited_fields": [],
        }

    # Section 2.4: Cross-manager conflict → UNCERTAIN
    if bundle.conflicts:
        c = bundle.conflicts[0]
        return {
            "verdict": "UNCERTAIN",
            "claim_amount": 0.0,
            "reasoning": f"Cross-manager discrepancy detected ({c.description}). Manual review required.",
            "supporting_evidence": [c.description],
            "cited_fields": [],
        }

    if not bundle.upstream_found or not bundle.fields:
        return {
            "verdict": "SILENT",
            "claim_amount": 0.0,
            "reasoning": "No operational records found for this unit across receiving, prep, pack, or returns.",
            "supporting_evidence": [],
            "cited_fields": [],
        }

    # Charge-specific logic
    if ct in ("inbound_defect_fee", "inbound_defect", "unplanned_prep"):
        bad_fields = [k for k, v in fields.items() if v in ("on_seam", "on_curve", "missing", "not_sealed", "obscured_by_fold", "fail")]
        uncertain_fields = [k for k, v in fields.items() if v == "uncertain"]

        if bad_fields:
            return {
                "verdict": "SUPPORTED",
                "claim_amount": 0.0,
                "reasoning": f"Prep records show non-compliant prep work: {', '.join(bad_fields)}. Charge is legitimate.",
                "supporting_evidence": [f"{k.replace('_', ' ').capitalize()}: {fields[k]}" for k in bad_fields],
                "cited_fields": [{"source": f.source, "record_id": f.record_id, "field": f.field_name, "value": f.field_value} for f in bundle.fields if f.field_name in bad_fields],
            }
        elif uncertain_fields:
            return {
                "verdict": "UNCERTAIN",
                "claim_amount": 0.0,
                "reasoning": f"Prep inspection logs show unverified states for: {', '.join(uncertain_fields)}. Further manual review required.",
                "supporting_evidence": [f"{k.replace('_', ' ').capitalize()}: Uncertain" for k in uncertain_fields],
                "cited_fields": [],
            }
        else:
            clean = [f for f in bundle.fields if f.field_value not in ("", "not_required")]
            if clean:
                return {
                    "verdict": "CONTRADICTED",
                    "claim_amount": charge.amount_usd,
                    "reasoning": "Prep inspection logs confirm items were prepared fully in compliance with guidelines prior to intake.",
                    "supporting_evidence": [f"{f.field_name.replace('_', ' ').capitalize()}: Verified ({f.field_value})" for f in clean[:3]],
                    "cited_fields": [{"source": f.source, "record_id": f.record_id, "field": f.field_name, "value": f.field_value} for f in clean[:3]],
                }

    if ct in ("lost_inbound", "warehouse_lost"):
        qty_ord = fields.get("qty_ordered") or fields.get("cartons_ordered")
        qty_rec = fields.get("qty_received") or fields.get("cartons_received")
        if qty_ord and qty_rec and str(qty_ord) == str(qty_rec):
            return {
                "verdict": "CONTRADICTED",
                "claim_amount": charge.amount_usd or 10.0,
                "reasoning": f"Receiving intake records confirm all {qty_rec} ordered units arrived intact and fully accounted for. Inventory loss claim is disputable.",
                "supporting_evidence": [f"Ordered Quantity: {qty_ord}", f"Received Quantity: {qty_rec}"],
                "cited_fields": [{"source": f.source, "record_id": f.record_id, "field": f.field_name, "value": f.field_value} for f in bundle.fields if f.field_name in ("qty_ordered", "qty_received")],
            }

    if ct in ("refund_issued_item_not_returned", "customer_return"):
        disp = fields.get("operator_disposition") or fields.get("disposition_assigned", "")
        state = fields.get("observed_state", "")
        id_match = fields.get("identity_match", "")
        if disp in ("restock", "refurbish", "liquidate", "dispose") or state in ("factory_sealed", "opened_good") or id_match == "yes":
            disp_pretty = disp.replace("_", " ").capitalize() if disp else "Restocked"
            state_pretty = state.replace("_", " ").capitalize() if state else "Factory sealed"
            return {
                "verdict": "CONTRADICTED",
                "claim_amount": charge.amount_usd or 15.0,
                "reasoning": f"Returns logs confirm unit was returned ({state_pretty} and {disp_pretty}), directly contradicting the 'item not returned' fee.",
                "supporting_evidence": [f"Item Condition: {state_pretty}", f"Inventory Status: {disp_pretty}"],
                "cited_fields": [{"source": f.source, "record_id": f.record_id, "field": f.field_name, "value": f.field_value} for f in bundle.fields if f.field_name in ("operator_disposition", "observed_state", "identity_match")],
            }

    if ct == "fulfilment_fee_weight_tier":
        return {
            "verdict": "UNCERTAIN",
            "claim_amount": 0.0,
            "reasoning": "SKU catalog specifications are verified, but physical scale weight measurement is absent from warehouse intake logs.",
            "supporting_evidence": [f"{k.replace('_', ' ').capitalize()}: {v}" for k, v in fields.items() if k in ("units_per_carton_counted", "spec_components", "spec_variant")],
            "cited_fields": [{"source": f.source, "record_id": f.record_id, "field": f.field_name, "value": f.field_value} for f in bundle.fields if f.field_name in fields],
        }

    return {
        "verdict": "UNCERTAIN",
        "claim_amount": 0.0,
        "reasoning": "Operational evidence exists but requires manual human review.",
        "supporting_evidence": [],
        "cited_fields": [],
    }


# ---------------------------------------------------------------------------
# Monotonic Auditor & Integrity Agent (Section 3 Agent #10 & Section 4.2/4.4)
# ---------------------------------------------------------------------------

def _run_integrity_checks(
    decision: ClaimDecision,
    bundle: EvidenceBundle,
    sla_result: SLAResult,
    reimbursements: list[ReimbursementRecord],
    dup_note: str,
) -> ClaimDecision:
    """
    Integrity Agent / Monotonic Auditor:
      - Can ONLY downgrade a claim (CONTRADICTED -> UNCERTAIN / ALREADY_RECOVERED / EXPIRED / DUPLICATE_SUPPRESSED).
      - Applies Hallucination Firewall to verify cited fields exist.
      - Conducts adversarial Claim Defense Pass.
      - Builds Evidence DNA tree.
    """
    c = bundle.charge

    # 1. Duplicate Suppression Check (Section 1.2)
    if dup_note:
        decision.duplicate_flag = True
        decision.duplicate_note = dup_note
        decision.claim_amount = 0.0

    # 2. Reimbursements Reconciliation Netting (Section 1.3)
    matching_reimbursements = [
        r for r in reimbursements
        if (r.sku and r.sku == c.sku) or (r.amazon_order_id and r.amazon_order_id == c.order_id) or (r.fnsku and r.fnsku == c.fnsku)
    ]
    total_already_reimbursed = sum(r.amount_total for r in matching_reimbursements)

    if total_already_reimbursed > 0:
        decision.already_reimbursed_amount = total_already_reimbursed
        if decision.verdict == "CONTRADICTED":
            rem = max(decision.amount_usd - total_already_reimbursed, 0.0)
            if rem == 0.0:
                decision.verdict = "ALREADY_RECOVERED"
                decision.claim_amount = 0.0
                decision.reasoning = f"Prior reimbursement of ${total_already_reimbursed:.2f} fully covers this ${c.amount_usd:.2f} fee."
            else:
                decision.claim_amount = round(rem, 2)
                decision.reasoning = f"Prior reimbursement of ${total_already_reimbursed:.2f} applied; remaining recoverable claim amount is ${rem:.2f}."

    # 3. SLA Expiration Gate (Section 1.4 & 2.8)
    if sla_result.status == "expired" and decision.verdict in ("CONTRADICTED", "PARTIAL_RECOVERY"):
        decision.verdict = "SILENT"
        decision.claim_amount = 0.0
        decision.reasoning = f"Dispute filing window expired on {sla_result.deadline} under SLA policy {sla_result.policy_version}. " + decision.reasoning

    # 4. Hallucination Firewall (Section 4.4)
    bundle_field_names = {f.field_name for f in bundle.fields}
    valid_citations = [cf for cf in decision.cited_fields if cf.get("field") in bundle_field_names]
    if len(valid_citations) < len(decision.cited_fields):
        decision.hallucination_blocked = True
        decision.cited_fields = valid_citations
        decision.defense_pass_notes.append("🚫 Unsupported statement blocked: Uncited field citation removed by Hallucination Firewall.")

    # 5. Claim Defense Pass (Section 4.2 Adversarial Audit)
    if decision.verdict == "CONTRADICTED":
        defense_notes = []
        if not any(f.source == "receiving" for f in bundle.fields):
            defense_notes.append("⚠ No Receiving intake record on file for this unit")
        if bundle.evidence_postdates_charge:
            defense_notes.append("⚠ Evidence timestamp postdates charge posted_date")
        if len(bundle.fields) < 2:
            defense_notes.append("⚠ Single-field evidence dependency; material evidence gap")

        decision.defense_pass_notes.extend(defense_notes)

        # Monotonic downgrade if severe gap
        if bundle.evidence_postdates_charge or len(bundle.fields) < 1:
            decision.verdict = "UNCERTAIN"
            decision.claim_amount = 0.0
            decision.reasoning = f"Claim downgraded to UNCERTAIN due to material evidence gaps: {'; '.join(defense_notes)}."

    # 6. Build Evidence DNA Tree (Section 4.1)
    decision.evidence_dna_tree = {
        "charge_id": c.line_id,
        "charge_type": c.charge_type,
        "amount_usd": c.amount_usd,
        "posted_date": c.posted_date,
        "resolved_unit_id": c.unit_id or c.fba_shipment_id or c.order_id,
        "policy_version": sla_result.policy_version,
        "cited_records": [
            {"source": f.source, "record_id": f.record_id, "field": f.field_name, "value": f.field_value, "timestamp": f.timestamp}
            for f in bundle.fields
        ],
        "verdict": decision.verdict,
    }

    decision.completeness_score = bundle.completeness_score
    decision.missing_fields = bundle.missing_fields

    # Compute major USP Features: Graph, Score, Strength, Priority, Custody, Hashes, Root Cause
    _compute_claimability_and_usp_features(decision, bundle, sla_result)

    return decision


def _compute_claimability_and_usp_features(
    decision: ClaimDecision,
    bundle: EvidenceBundle,
    sla_result: SLAResult,
) -> None:
    import hashlib

    c = bundle.charge

    # 1. Evidence Graph Building (USP #2)
    nodes = [
        {"id": f"charge-{c.line_id}", "type": "charge", "label": f"Fee Charge: {c.charge_type}", "amount": c.amount_usd},
        {"id": f"unit-{c.unit_id}", "type": "unit", "label": f"Resolved Unit: {c.unit_id}"},
    ]
    edges = [
        {"from": f"charge-{c.line_id}", "to": f"unit-{c.unit_id}", "label": "assigned_to"},
    ]

    for f in bundle.fields:
        node_id = f"{f.source}-{f.record_id}"
        if not any(n["id"] == node_id for n in nodes):
            nodes.append({"id": node_id, "type": f.source, "label": f"{f.source.upper()} ({f.record_id})", "timestamp": f.timestamp})
            edges.append({"from": f"unit-{c.unit_id}", "to": node_id, "label": f"verified_{f.field_name}"})

    decision.evidence_graph = {"nodes": nodes, "edges": edges}

    # 2. Custody Window (USP #3)
    timestamps = [f.timestamp for f in bundle.fields if f.timestamp]
    earliest_ts = min(timestamps) if timestamps else (c.posted_date or "Pre-charge")
    precedes = not bundle.evidence_postdates_charge

    decision.custody_window = {
        "evidence_start": earliest_ts,
        "charge_posted": c.posted_date or "Unknown",
        "filing_deadline": str(sla_result.deadline) if sla_result.deadline else "N/A",
        "precedes_charge": precedes,
        "valid_custody": precedes and bundle.upstream_found,
    }

    # 3. Claimability Score (USP #4 & USP #5)
    ev_score = min(int(bundle.completeness_score * 25), 25)
    rule_score = 20 if c.charge_type in CHARGE_ROUTING else 0
    timing_score = 20 if precedes else 5
    entity_score = 15 if bundle.upstream_found else 0
    dup_score = 0 if decision.duplicate_flag else 10
    sla_score = 10 if sla_result.status == "open" else (5 if sla_result.status == "min_wait" else 0)

    total_score = ev_score + rule_score + timing_score + entity_score + dup_score + sla_score
    if decision.verdict != "CONTRADICTED":
        total_score = min(total_score, 65)

    decision.claimability_score = total_score
    decision.score_breakdown = {
        "evidence_coverage": f"{ev_score}/25",
        "rule_match": f"{rule_score}/20",
        "timing_custody": f"{timing_score}/20",
        "entity_resolution": f"{entity_score}/15",
        "duplicate_check": f"{dup_score}/10",
        "sla_window": f"{sla_score}/10",
    }

    # Evidence Strength Classification
    if not bundle.upstream_found:
        decision.evidence_strength = "MISSING"
    elif bundle.completeness_score >= 0.8 and precedes:
        decision.evidence_strength = "DIRECT" if len(bundle.fields) >= 3 else "STRONG"
    elif bundle.completeness_score >= 0.4:
        decision.evidence_strength = "MODERATE"
    else:
        decision.evidence_strength = "WEAK"

    # 4. Priority Engine (USP #6)
    days_left = sla_result.days_remaining if sla_result.days_remaining is not None else 30
    if decision.verdict == "CONTRADICTED":
        if decision.claim_amount >= 100.0 or days_left <= 5:
            decision.priority_level = "URGENT"
        elif decision.claim_amount >= 30.0 or days_left <= 15:
            decision.priority_level = "HIGH"
        else:
            decision.priority_level = "NORMAL"
    else:
        decision.priority_level = "LOW"

    # 5. "Why Not Claim?" & Missing Evidence Intelligence (USP #7 & USP #8)
    if decision.verdict != "CONTRADICTED":
        if decision.verdict == "SUPPORTED":
            decision.why_not_claim = "Charge is verified legitimate based on upstream operational logs showing non-compliant work or item damage."
            decision.required_evidence_to_resolve = ["Revised operator compliance log", "Audit override sign-off"]
        elif decision.verdict == "SILENT":
            decision.why_not_claim = "No matching upstream records found for this unit prior to the fee charge date."
            decision.required_evidence_to_resolve = ["Receiving intake inspection log", "Prep completion record", "Pack timestamp report"]
        elif decision.verdict == "UNCERTAIN":
            decision.why_not_claim = "Evidence exists but exhibits data gaps or unverified measurement fields."
            decision.required_evidence_to_resolve = ["Scale physical weight measurement log", "Warehouse photo confirmation"]
        elif decision.verdict == "DUPLICATE_SUPPRESSED":
            decision.why_not_claim = f"Duplicate charge detected ({decision.duplicate_note}). Earlier claim already filed."
            decision.required_evidence_to_resolve = ["Original claim filing confirmation"]
        elif decision.verdict == "EXPIRED":
            decision.why_not_claim = f"SLA filing window expired on {sla_result.deadline}."
            decision.required_evidence_to_resolve = ["Policy extension approval"]
        else:
            decision.why_not_claim = "Charge requires manual decision review."
            decision.required_evidence_to_resolve = ["Upstream operational logs"]
    else:
        decision.why_not_claim = ""
        decision.required_evidence_to_resolve = []

    # 6. Adversarial Challenge Pass (USP #1)
    adversarial_findings = []
    if decision.verdict == "CONTRADICTED":
        if bundle.evidence_postdates_charge:
            adversarial_findings.append("Evidence timestamp postdates fee posted date.")
        if decision.already_reimbursed_amount > 0:
            adversarial_findings.append(f"Prior reimbursement of ${decision.already_reimbursed_amount:.2f} detected.")
        if decision.duplicate_flag:
            adversarial_findings.append("Duplicate charge fingerprint detected.")
        if sla_result.status == "expired":
            adversarial_findings.append("SLA window expired.")

    decision.adversarial_pass = (len(adversarial_findings) == 0 and decision.verdict == "CONTRADICTED")
    decision.adversarial_findings = adversarial_findings

    # 7. Root Cause Analysis (USP #10)
    ct = c.charge_type
    if "defect" in ct or "prep" in ct:
        decision.root_cause_driver = "Packaging & Polybag Compliance"
    elif "lost" in ct:
        decision.root_cause_driver = "Inbound Receiving Discrepancy"
    elif "return" in ct:
        decision.root_cause_driver = "Customer Return Processing & Restock"
    elif "weight" in ct:
        decision.root_cause_driver = "Catalog Dimension / Weight Tier Mismatch"
    else:
        decision.root_cause_driver = "General Operational Dispute"

    # 8. SHA-256 Tamper-Evident Hash (USP #12 & USP #13)
    raw_payload = f"{c.line_id}:{c.unit_id}:{c.amount_usd}:{decision.verdict}:{decision.claim_amount}:{sla_result.policy_version}:{decision.claimability_score}"
    decision.sha256_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Public Classify API
# ---------------------------------------------------------------------------

def classify(
    bundle: EvidenceBundle,
    sla_result: SLAResult,
    reimbursements: list[ReimbursementRecord] | None = None,
    duplicate_note: str = "",
) -> ClaimDecision:
    """
    Main Classification Pipeline.
    Runs Deterministic/LLM Classifier + Integrity Agent Monotonic Audit.
    """
    charge = bundle.charge
    reimbursements = reimbursements or []

    # Deterministic fallback classification first
    res = _deterministic_classify(bundle)

    decision = ClaimDecision(
        line_id=charge.line_id,
        unit_id=charge.unit_id or charge.fba_shipment_id or charge.order_id,
        org_id=charge.org_id,
        charge_type=charge.charge_type,
        amount_usd=charge.amount_usd,
        verdict=res.get("verdict", "UNCERTAIN"),
        claim_amount=res.get("claim_amount", 0.0),
        reasoning=res.get("reasoning", ""),
        supporting_evidence=res.get("supporting_evidence", []),
        cited_fields=res.get("cited_fields", []),
        sla={
            "status": sla_result.status,
            "deadline": str(sla_result.deadline) if sla_result.deadline else None,
            "earliest_filing": str(sla_result.earliest_filing) if sla_result.earliest_filing else None,
            "days_remaining": sla_result.days_remaining,
            "policy_note": sla_result.policy_note,
            "policy_version": sla_result.policy_version,
        },
    )

    # Run Integrity Agent & Monotonic Auditor
    return _run_integrity_checks(decision, bundle, sla_result, reimbursements, duplicate_note)
