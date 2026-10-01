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
            "reasoning": f"NOT_YET_SUPPORTED: No evidence routing rule entry exists for charge_type {ct!r}.",
            "supporting_evidence": [],
            "cited_fields": [],
        }

    # Section 2.8: Evidence postdates charge → SILENT
    if bundle.evidence_postdates_charge:
        return {
            "verdict": "SILENT",
            "claim_amount": 0.0,
            "reasoning": "SILENT: Evidence record captured_at postdates the charge posted_date; cannot prove condition prior to charge.",
            "supporting_evidence": [],
            "cited_fields": [],
        }

    # Section 2.4: Cross-manager conflict → UNCERTAIN
    if bundle.conflicts:
        c = bundle.conflicts[0]
        return {
            "verdict": "UNCERTAIN",
            "claim_amount": 0.0,
            "reasoning": f"UNCERTAIN: Cross-manager contradiction detected ({c.description}). Manual investigation required.",
            "supporting_evidence": [c.description],
            "cited_fields": [],
        }

    if not bundle.upstream_found or not bundle.fields:
        return {
            "verdict": "SILENT",
            "claim_amount": 0.0,
            "reasoning": "SILENT: No upstream evidence found for this unit. Cannot support a claim.",
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
                "reasoning": f"Prep records show non-compliant fields: {bad_fields}. Charge appears legitimate.",
                "supporting_evidence": [f"{k}={fields[k]}" for k in bad_fields],
                "cited_fields": [{"source": f.source, "record_id": f.record_id, "field": f.field_name, "value": f.field_value} for f in bundle.fields if f.field_name in bad_fields],
            }
        elif uncertain_fields:
            return {
                "verdict": "UNCERTAIN",
                "claim_amount": 0.0,
                "reasoning": f"Prep records have uncertain values for: {uncertain_fields}. UNCERTAIN evidence cannot support a claim.",
                "supporting_evidence": [f"{k}=uncertain" for k in uncertain_fields],
                "cited_fields": [],
            }
        else:
            clean = [f for f in bundle.fields if f.field_value not in ("", "not_required")]
            if clean:
                return {
                    "verdict": "CONTRADICTED",
                    "claim_amount": charge.amount_usd,
                    "reasoning": "Prep records show compliant preparation. Inbound defect charge appears disputable.",
                    "supporting_evidence": [f"{f.field_name}={f.field_value}" for f in clean[:3]],
                    "cited_fields": [{"source": f.source, "record_id": f.record_id, "field": f.field_name, "value": f.field_value} for f in clean[:3]],
                }

    if ct in ("lost_inbound", "warehouse_lost"):
        qty_ord = fields.get("qty_ordered") or fields.get("cartons_ordered")
        qty_rec = fields.get("qty_received") or fields.get("cartons_received")
        if qty_ord and qty_rec and str(qty_ord) == str(qty_rec):
            return {
                "verdict": "CONTRADICTED",
                "claim_amount": charge.amount_usd or 10.0,  # default estimated unit value if 0.0 in adjustment
                "reasoning": f"Receiving record shows qty_received={qty_rec} matching qty_ordered={qty_ord}. Unit loss claim disputable.",
                "supporting_evidence": [f"qty_ordered={qty_ord}", f"qty_received={qty_rec}"],
                "cited_fields": [{"source": f.source, "record_id": f.record_id, "field": f.field_name, "value": f.field_value} for f in bundle.fields if f.field_name in ("qty_ordered", "qty_received")],
            }

    if ct in ("refund_issued_item_not_returned", "customer_return"):
        disp = fields.get("operator_disposition") or fields.get("disposition_assigned", "")
        state = fields.get("observed_state", "")
        id_match = fields.get("identity_match", "")
        if disp in ("restock", "refurbish", "liquidate", "dispose") or state in ("factory_sealed", "opened_good") or id_match == "yes":
            return {
                "verdict": "CONTRADICTED",
                "claim_amount": charge.amount_usd or 15.0,
                "reasoning": f"Returns record shows unit was returned (disposition={disp!r}, state={state!r}). Contradicts 'item not returned' charge.",
                "supporting_evidence": [f"operator_disposition={disp}", f"observed_state={state}"],
                "cited_fields": [{"source": f.source, "record_id": f.record_id, "field": f.field_name, "value": f.field_value} for f in bundle.fields if f.field_name in ("operator_disposition", "observed_state", "identity_match")],
            }

    # Section 1.1: fulfilment_fee_weight_tier -> Receiving spec fields
    if ct == "fulfilment_fee_weight_tier":
        spec_fields = {k: v for k, v in fields.items() if k in ("units_per_carton_counted", "spec_components", "spec_variant", "spec_colour", "sku")}
        return {
            "verdict": "UNCERTAIN",
            "claim_amount": 0.0,
            "reasoning": f"SKU confirmed via receiving spec fields ({spec_fields}), but physical scale weight measurement is missing from records. Manual weight verification required.",
            "supporting_evidence": [f"{k}={v}" for k, v in spec_fields.items()],
            "cited_fields": [{"source": f.source, "record_id": f.record_id, "field": f.field_name, "value": f.field_value} for f in bundle.fields if f.field_name in spec_fields],
        }

    return {
        "verdict": "UNCERTAIN",
        "claim_amount": 0.0,
        "reasoning": "Evidence exists but requires manual human review.",
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
                decision.reasoning = f"[ALREADY RECOVERED] Prior reimbursement of ${total_already_reimbursed:.2f} nets against this ${c.amount_usd:.2f} charge."
            else:
                decision.claim_amount = round(rem, 2)
                decision.reasoning = f"[PARTIAL RECOVERY] ${total_already_reimbursed:.2f} already reimbursed; remaining claimable amount: ${rem:.2f}."

    # 3. SLA Expiration Gate (Section 1.4 & 2.8)
    if sla_result.status == "expired" and decision.verdict in ("CONTRADICTED", "PARTIAL_RECOVERY"):
        decision.verdict = "SILENT"
        decision.claim_amount = 0.0
        decision.reasoning = f"[EXPIRED SLA / MISSED RECOVERABLE] Filing window expired on {sla_result.deadline} (SLA policy {sla_result.policy_version}). " + decision.reasoning

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
            decision.reasoning = f"[DEFENSE AUDIT DOWNGRADE] Claim downgraded to UNCERTAIN due to material evidence gaps: {'; '.join(defense_notes)}."

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

    return decision


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
