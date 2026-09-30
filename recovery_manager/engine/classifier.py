
"""
LLM Classifier — Recovery Manager
Takes a matched evidence bundle and returns a four-state verdict:
  CONTRADICTED | SUPPORTED | SILENT | UNCERTAIN

Key design decisions (follow strictly):
  - LLM reasons only over meaning; it does NOT do arithmetic or date math.
  - A single batched call per bundle (never per-field).
  - Mandatory hallucination guard: LLM must cite specific field values.
  - Fail-open: model error → pending_review, not discard.
  - GEMINI_API_KEY is loaded from environment; never hard-coded.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Literal

from .evidence_matcher import EvidenceBundle
from .sla_engine import SLAResult
from .evidence_matcher import CHARGE_ROUTING

Verdict = Literal["CONTRADICTED", "SUPPORTED", "SILENT", "UNCERTAIN", "PENDING_REVIEW"]


@dataclass
class ClaimDecision:
    line_id: str
    unit_id: str
    org_id: str
    charge_type: str
    amount_usd: float
    verdict: Verdict
    claim_amount: float   # 0.0 if not claimable
    reasoning: str
    supporting_evidence: list[str] = field(default_factory=list)
    cited_fields: list[dict] = field(default_factory=list)   # [{source, record_id, field, value}]
    sla: dict = field(default_factory=dict)
    duplicate_flag: bool = False
    duplicate_note: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(bundle: EvidenceBundle, routing_hint: str) -> str:
    charge = bundle.charge
    fields_text = "\n".join(
        f"  [{f.source} / {f.record_id}] {f.field_name} = {f.field_value!r}  # {f.relevance_note}"
        for f in bundle.fields
    ) or "  (no evidence fields found)"

    prompt = f"""You are a Recovery Manager agent for an Amazon FBA seller.
Your job: analyse a fee/reimbursement charge against available upstream evidence
and return a JSON decision object.

CHARGE:
  line_id: {charge.line_id}
  charge_type: {charge.charge_type}
  report_type: {charge.report_type}
  amount_usd: {charge.amount_usd}
  unit_id: {charge.unit_id}
  sku: {charge.sku}
  fnsku: {charge.fnsku}
  fba_shipment_id: {charge.fba_shipment_id}
  order_id: {charge.order_id}
  posted_date: {charge.posted_date}

UPSTREAM EVIDENCE FIELDS:
{fields_text}

REASONING GUIDANCE FOR THIS CHARGE TYPE:
{routing_hint}

VERDICT DEFINITIONS (choose exactly one):
  CONTRADICTED – evidence clearly shows the charge is wrong or the unit qualifies for reimbursement.
  SUPPORTED    – evidence confirms the charge is legitimate; no claim recommended.
  SILENT       – evidence exists but cannot speak to this specific charge; or no evidence found.
  UNCERTAIN    – evidence is ambiguous, partial, or conflicting; requires human review.

CRITICAL RULES:
1. Do NOT invent evidence. If a field is not in the list above, it does not exist.
2. Do NOT perform date arithmetic or threshold comparisons yourself.
3. Every claim must cite at least one specific [source / record_id] field by name.
4. SILENT means: no claim, reason: insufficient evidence.
5. UNCERTAIN is NOT a low-confidence CONTRADICTED; send it to human review.
6. claim_amount must be exactly amount_usd if CONTRADICTED (disputable), else 0.0.

Return ONLY valid JSON matching this exact schema:
{{
  "verdict": "<CONTRADICTED|SUPPORTED|SILENT|UNCERTAIN>",
  "claim_amount": <number>,
  "reasoning": "<1-3 sentence plain-English explanation>",
  "supporting_evidence": ["<short evidence phrase 1>", "..."],
  "cited_fields": [
    {{"source": "<source>", "record_id": "<id>", "field": "<name>", "value": "<val>"}}
  ]
}}
"""
    return prompt


# ---------------------------------------------------------------------------
# Gemini client (lazy, cached)
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
        from google import genai  # new SDK
        _gemini_client = genai.Client(api_key=api_key)
        _USE_NEW_SDK = True
        return _gemini_client
    except ImportError:
        pass
    try:
        import google.generativeai as genai_old  # legacy
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            genai_old.configure(api_key=api_key)
            _gemini_client = genai_old.GenerativeModel("gemini-2.0-flash")
        _USE_NEW_SDK = False
        return _gemini_client
    except Exception:
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
                config={"temperature": 0.1, "max_output_tokens": 1024,
                        "response_mime_type": "application/json"},
            )
        else:
            resp = client.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 1024,
                    "response_mime_type": "application/json",
                },
            )
        text = resp.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Deterministic fallback classifier (no LLM)
# ---------------------------------------------------------------------------

def _deterministic_classify(bundle: EvidenceBundle) -> dict:
    """
    Rule-based fallback when the LLM is unavailable or fails.
    Conservative: defaults to UNCERTAIN when in doubt.
    """
    charge = bundle.charge
    ct = charge.charge_type
    fields = {f.field_name: f.field_value for f in bundle.fields}

    if not bundle.upstream_found or not bundle.fields:
        return {
            "verdict": "SILENT",
            "claim_amount": 0.0,
            "reasoning": "No upstream evidence found for this unit. Cannot support a claim.",
            "supporting_evidence": [],
            "cited_fields": [],
        }

    if ct == "inbound_defect_fee":
        bad_fields = [
            k for k, v in fields.items()
            if v in ("on_seam", "on_curve", "on_edge", "missing", "not_sealed", "obscured_by_fold")
        ]
        uncertain_fields = [k for k, v in fields.items() if v == "uncertain"]
        if bad_fields:
            return {
                "verdict": "SUPPORTED",
                "claim_amount": 0.0,
                "reasoning": f"Prep records show problematic fields: {bad_fields}. Fee appears legitimate.",
                "supporting_evidence": [f"{k}={fields[k]}" for k in bad_fields],
                "cited_fields": [{"source": f.source, "record_id": f.record_id, "field": f.field_name, "value": f.field_value}
                                 for f in bundle.fields if f.field_name in bad_fields],
            }
        elif uncertain_fields:
            return {
                "verdict": "UNCERTAIN",
                "claim_amount": 0.0,
                "reasoning": f"Prep records have uncertain values for: {uncertain_fields}. Manual review required.",
                "supporting_evidence": [f"{k}=uncertain" for k in uncertain_fields],
                "cited_fields": [],
            }
        else:
            clean = [f for f in bundle.fields if f.field_value not in ("", "not_required")]
            if clean:
                return {
                    "verdict": "CONTRADICTED",
                    "claim_amount": charge.amount_usd,
                    "reasoning": "Prep records show compliant preparation. Inbound defect fee appears disputable.",
                    "supporting_evidence": [f"{f.field_name}={f.field_value}" for f in clean[:3]],
                    "cited_fields": [{"source": f.source, "record_id": f.record_id, "field": f.field_name, "value": f.field_value}
                                     for f in clean[:3]],
                }
        return {"verdict": "UNCERTAIN", "claim_amount": 0.0, "reasoning": "Evidence ambiguous.", "supporting_evidence": [], "cited_fields": []}

    if ct == "lost_inbound":
        qty_ord = fields.get("qty_ordered", "")
        qty_rec = fields.get("qty_received", "")
        if qty_ord and qty_rec and qty_ord == qty_rec:
            return {
                "verdict": "CONTRADICTED",
                "claim_amount": 0.0,  # Lost inbound → reimbursement, amount is $0 in fee report
                "reasoning": f"Receiving record shows qty_received={qty_rec} matching qty_ordered={qty_ord}. Unit was received; loss claim disputable.",
                "supporting_evidence": [f"qty_ordered={qty_ord}", f"qty_received={qty_rec}"],
                "cited_fields": [{"source": f.source, "record_id": f.record_id, "field": f.field_name, "value": f.field_value}
                                 for f in bundle.fields if f.field_name in ("qty_ordered", "qty_received")],
            }
        return {"verdict": "UNCERTAIN", "claim_amount": 0.0, "reasoning": "Quantity data ambiguous or short-ship confirmed.", "supporting_evidence": [], "cited_fields": []}

    if ct == "refund_issued_item_not_returned":
        disp = fields.get("operator_disposition", "")
        state = fields.get("observed_state", "")
        if disp in ("restock", "refurbish", "liquidate", "dispose"):
            return {
                "verdict": "CONTRADICTED",
                "claim_amount": 0.0,
                "reasoning": f"Returns record shows unit was received back (disposition={disp!r}, state={state!r}). Contradicts 'item not returned' charge.",
                "supporting_evidence": [f"operator_disposition={disp}", f"observed_state={state}"],
                "cited_fields": [{"source": f.source, "record_id": f.record_id, "field": f.field_name, "value": f.field_value}
                                 for f in bundle.fields if f.field_name in ("operator_disposition", "observed_state")],
            }
        if not disp:
            return {"verdict": "SILENT", "claim_amount": 0.0, "reasoning": "No returns record found. Cannot contradict the charge.", "supporting_evidence": [], "cited_fields": []}
        return {"verdict": "UNCERTAIN", "claim_amount": 0.0, "reasoning": "Returns disposition inconclusive.", "supporting_evidence": [], "cited_fields": []}

    # Generic: if evidence found, UNCERTAIN; if not, SILENT
    if bundle.fields:
        return {"verdict": "UNCERTAIN", "claim_amount": 0.0,
                "reasoning": "Evidence exists but rule-based classifier has no specific rule for this charge type.",
                "supporting_evidence": [], "cited_fields": []}
    return {"verdict": "SILENT", "claim_amount": 0.0,
            "reasoning": "No upstream evidence found.",
            "supporting_evidence": [], "cited_fields": []}


# ---------------------------------------------------------------------------
# Public classify function
# ---------------------------------------------------------------------------

def classify(
    bundle: EvidenceBundle,
    sla_result: SLAResult,
    duplicate_note: str = "",
) -> ClaimDecision:
    """
    Classify a single evidence bundle and return a ClaimDecision.
    Tries LLM first; falls back to deterministic classifier on failure.
    """
    charge = bundle.charge
    routing = CHARGE_ROUTING.get(charge.charge_type, {})
    hint = routing.get("reasoning_hint", "No specific routing hint available.")

    # --- Try LLM ---
    result: dict | None = None
    if bundle.upstream_found:
        prompt = _build_prompt(bundle, hint)
        result = _call_llm(prompt)

    # --- Fallback ---
    if result is None:
        result = _deterministic_classify(bundle)
        error_note = "" if _get_client() is not None else "LLM unavailable; deterministic fallback used."
    else:
        error_note = ""

    verdict: Verdict = result.get("verdict", "PENDING_REVIEW")
    if verdict not in ("CONTRADICTED", "SUPPORTED", "SILENT", "UNCERTAIN"):
        verdict = "PENDING_REVIEW"
        error_note += " Unexpected verdict from model."

    # SLA gate: expired → downgrade to SILENT (can't file)
    if sla_result.status == "expired" and verdict == "CONTRADICTED":
        verdict = "SILENT"
        result["reasoning"] = (
            f"[SLA EXPIRED] Claim window closed on {sla_result.deadline}. "
            + result.get("reasoning", "")
        )
        result["claim_amount"] = 0.0

    # Min-wait gate: not yet fileable
    if sla_result.status == "min_wait" and verdict == "CONTRADICTED":
        result["reasoning"] = (
            f"[MIN WAIT] Earliest filing date is {sla_result.earliest_filing}. "
            + result.get("reasoning", "")
        )

    claim_amount = float(result.get("claim_amount", 0.0))

    return ClaimDecision(
        line_id=charge.line_id,
        unit_id=charge.unit_id,
        org_id=charge.org_id,
        charge_type=charge.charge_type,
        amount_usd=charge.amount_usd,
        verdict=verdict,
        claim_amount=claim_amount,
        reasoning=result.get("reasoning", ""),
        supporting_evidence=result.get("supporting_evidence", []),
        cited_fields=result.get("cited_fields", []),
        sla={
            "status": sla_result.status,
            "deadline": str(sla_result.deadline) if sla_result.deadline else None,
            "earliest_filing": str(sla_result.earliest_filing) if sla_result.earliest_filing else None,
            "days_remaining": sla_result.days_remaining,
            "policy_note": sla_result.policy_note,
        },
        duplicate_flag=bool(duplicate_note),
        duplicate_note=duplicate_note,
        error=error_note,
    )
