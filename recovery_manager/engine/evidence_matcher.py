"""
Evidence Matcher — Recovery Manager
Maps each charge_type to the relevant upstream evidence fields,
then produces a deterministic evidence summary for the LLM classifier.

No model calls happen here — this module is pure deterministic logic.
The LLM receives the output of this module and reasons over it.
"""

from dataclasses import dataclass, field
from typing import Any

from .ingestor import FeeCharge, UpstreamBundle


# ---------------------------------------------------------------------------
# Evidence summary data models
# ---------------------------------------------------------------------------

@dataclass
class EvidenceField:
    source: str           # "prep" | "receiving" | "pack" | "returns"
    record_id: str
    field_name: str
    field_value: str
    relevance_note: str


@dataclass
class EvidenceBundle:
    charge: FeeCharge
    unit_id: str
    upstream_found: bool
    fields: list[EvidenceField] = field(default_factory=list)
    raw_upstream: dict = field(default_factory=dict)   # for traceability
    duplicate_detected: bool = False
    duplicate_note: str = ""


# ---------------------------------------------------------------------------
# Routing table — maps charge_type to which sources matter and what to look at
# ---------------------------------------------------------------------------

CHARGE_ROUTING: dict[str, dict] = {
    "inbound_defect_fee": {
        "primary_source": "prep",
        "secondary_sources": ["receiving"],
        "prep_fields": [
            "polybag_present_sealed",
            "suffocation_warning",
            "fnsku_label_placement",
            "original_barcode_covered",
            "expiry_date",
            "handling_marks",
        ],
        "receiving_fields": ["carton_damage", "unit_damage", "quality_flags"],
        "reasoning_hint": (
            "An inbound defect fee alleges the unit arrived at Amazon non-compliant. "
            "Prep records showing PASS on all checked fields CONTRADICT the fee. "
            "Prep records with FAIL or UNCERTAIN fields may SUPPORT or leave it UNCERTAIN. "
            "No prep record → SILENT."
        ),
    },
    "lost_inbound": {
        "primary_source": "receiving",
        "secondary_sources": ["prep"],
        "receiving_fields": [
            "qty_ordered",
            "qty_received",
            "identity_match",
            "carton_damage",
        ],
        "prep_fields": ["fba_shipment_id"],
        "reasoning_hint": (
            "A lost_inbound adjustment means the channel claims it never received the unit. "
            "A receiving record showing qty_received matching qty_ordered CONTRADICTS the loss "
            "claim (unit was present at supplier handoff). "
            "Short shipment at receiving supports the channel's position. "
            "No receiving record → SILENT."
        ),
    },
    "damaged_in_warehouse": {
        "primary_source": "receiving",
        "secondary_sources": ["prep", "returns"],
        "receiving_fields": ["carton_damage", "unit_damage", "quality_flags", "identity_match"],
        "prep_fields": ["polybag_present_sealed"],
        "returns_fields": ["observed_state", "amazon_condition", "operator_disposition"],
        "reasoning_hint": (
            "A damaged_in_warehouse claim means the channel damaged our unit. "
            "Receiving showing no damage on arrival SUPPORTS a reimbursement claim. "
            "Returns showing unit arrived damaged (observed_state=damaged) may corroborate. "
            "No clean receiving record → UNCERTAIN or SILENT."
        ),
    },
    "fulfilment_fee_weight_tier": {
        "primary_source": "prep",
        "secondary_sources": ["receiving"],
        "prep_fields": ["sku", "fnsku", "fba_shipment_id"],
        "receiving_fields": ["sku", "asin", "product_title"],
        "reasoning_hint": (
            "A fulfilment_fee_weight_tier charge may be overcharged if the SKU's actual weight/size "
            "places it in a lower tier. Evidence here is structural: we can confirm SKU identity "
            "but cannot measure physical weight from upstream records. "
            "If SKU confirmed, flag for manual weight verification. "
            "If SKU cannot be confirmed → UNCERTAIN."
        ),
    },
    "refund_issued_item_not_returned": {
        "primary_source": "returns",
        "secondary_sources": ["pack"],
        "returns_fields": [
            "identity_match",
            "observed_state",
            "amazon_condition",
            "operator_disposition",
            "parts_missing",
        ],
        "pack_fields": ["operator_verdict", "order_lines", "observed_in_box"],
        "reasoning_hint": (
            "This charge claims the channel issued a refund but the unit was never returned. "
            "A returns record for this unit/order CONTRADICTS the charge (unit was actually returned). "
            "Returns record showing disposition=restock or refurbish strongly contradicts. "
            "No returns record → the claim that nothing was returned may be correct → SILENT."
        ),
    },
}

DEFAULT_ROUTING = {
    "primary_source": "receiving",
    "secondary_sources": [],
    "reasoning_hint": "No specific routing rule for this charge type; using receiving as fallback.",
}


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------

def _extract_fields(
    source_name: str,
    record: dict,
    field_names: list[str],
    relevance_note: str,
) -> list[EvidenceField]:
    result = []
    rid = record.get("record_id", f"{source_name}-unknown")
    for fn in field_names:
        val = record.get(fn, "")
        if val is not None:
            result.append(EvidenceField(
                source=source_name,
                record_id=rid,
                field_name=fn,
                field_value=str(val),
                relevance_note=relevance_note,
            ))
    return result


def match_charge(
    charge: FeeCharge,
    upstream: UpstreamBundle | None,
    known_line_ids: set[str] | None = None,
) -> EvidenceBundle:
    """
    Match a single FeeCharge to its upstream evidence.
    Returns an EvidenceBundle with all relevant fields extracted.
    """
    bundle = EvidenceBundle(
        charge=charge,
        unit_id=charge.unit_id,
        upstream_found=upstream is not None,
        raw_upstream=upstream.as_dict() if upstream else {},
    )

    if upstream is None:
        return bundle

    routing = CHARGE_ROUTING.get(charge.charge_type, DEFAULT_ROUTING)
    primary = routing["primary_source"]
    secondaries = routing.get("secondary_sources", [])

    source_map = {
        "prep": upstream.prep,
        "receiving": upstream.receiving,
        "pack": upstream.pack,
        "returns": upstream.returns,
    }

    # Extract primary source fields
    primary_field_key = f"{primary}_fields"
    primary_fields = routing.get(primary_field_key, [])
    for record in source_map.get(primary, []):
        bundle.fields.extend(_extract_fields(
            primary, record, primary_fields,
            f"Primary evidence for {charge.charge_type}",
        ))

    # Extract secondary source fields
    for sec in secondaries:
        sec_field_key = f"{sec}_fields"
        sec_fields = routing.get(sec_field_key, [])
        for record in source_map.get(sec, []):
            bundle.fields.extend(_extract_fields(
                sec, record, sec_fields,
                f"Secondary evidence for {charge.charge_type}",
            ))

    return bundle


def detect_duplicates(
    charges: list[FeeCharge],
) -> dict[str, str]:
    """
    Detect charges that appear to be duplicates of each other.
    Returns a dict of line_id → duplicate_note.
    Same unit_id + charge_type + amount within 30 days = potential duplicate.
    """
    from collections import defaultdict
    from datetime import date, timedelta

    duplicates: dict[str, str] = {}
    groups: dict[tuple, list[FeeCharge]] = defaultdict(list)

    for c in charges:
        key = (c.unit_id, c.charge_type)
        groups[key].append(c)

    for key, group in groups.items():
        if len(group) < 2:
            continue
        # Check if any two share same amount within 30 days
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if a.amount_usd != b.amount_usd or a.amount_usd == 0.0:
                    continue
                try:
                    da = date.fromisoformat(a.posted_date[:10])
                    db = date.fromisoformat(b.posted_date[:10])
                except (ValueError, IndexError):
                    continue
                if abs((da - db).days) <= 30:
                    duplicates[a.line_id] = f"Possible duplicate of {b.line_id} (same unit, type, amount within 30 days)"
                    duplicates[b.line_id] = f"Possible duplicate of {a.line_id} (same unit, type, amount within 30 days)"

    return duplicates
