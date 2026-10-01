"""
Evidence Matcher & Planner — Recovery Manager
Maps each charge_type to relevant upstream evidence fields across Receiving, Prep, Pack, and Returns.
Extracts evidence, checks timestamps, and builds a rich EvidenceBundle.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .ingestor import FeeCharge, UpstreamBundle


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class EvidenceField:
    source: str           # "prep" | "receiving" | "pack" | "returns"
    record_id: str
    field_name: str
    field_value: str
    relevance_note: str
    timestamp: str = ""   # captured_at


@dataclass
class EvidenceConflict:
    source_a: str
    source_b: str
    record_a: str
    record_b: str
    conflict_type: str
    description: str


@dataclass
class EvidenceBundle:
    charge: FeeCharge
    unit_id: str
    upstream_found: bool
    fields: list[EvidenceField] = field(default_factory=list)
    raw_upstream: dict = field(default_factory=dict)
    conflicts: list[EvidenceConflict] = field(default_factory=list)
    duplicate_detected: bool = False
    duplicate_note: str = ""
    evidence_postdates_charge: bool = False
    completeness_score: float = 0.0   # 0.0 - 1.0 completeness gap indicator
    missing_fields: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Routing table — Contract v1.1 Registry Check Keys
# ---------------------------------------------------------------------------

CHARGE_ROUTING: dict[str, dict] = {
    "inbound_defect_fee": {
        "primary_source": "prep",
        "secondary_sources": ["receiving"],
        "prep_fields": [
            "polybag_present", "polybag_sealed", "suffocation_warning_present",
            "suffocation_warning_legible", "fnsku_label_flat", "fnsku_label_placement_valid",
            "manufacturer_barcode_covered", "expiry_date_legible", "handling_marks_present",
            "polybag_present_sealed", "suffocation_warning", "fnsku_label_placement", "original_barcode_covered"
        ],
        "receiving_fields": ["carton_damage", "unit_damage", "quality_flags", "unit_undamaged"],
        "reasoning_hint": (
            "An inbound defect fee alleges the unit arrived non-compliant. "
            "Prep records showing PASS on all checked fields CONTRADICT the fee. "
            "Prep records with FAIL fields SUPPORT the charge. "
            "No prep record → SILENT / INSUFFICIENT_EVIDENCE."
        ),
    },
    "inbound_defect": {
        "primary_source": "prep",
        "secondary_sources": ["receiving"],
        "prep_fields": [
            "polybag_present", "polybag_sealed", "suffocation_warning_present",
            "suffocation_warning_legible", "fnsku_label_flat", "fnsku_label_placement_valid",
            "manufacturer_barcode_covered", "polybag_present_sealed", "suffocation_warning", "fnsku_label_placement"
        ],
        "receiving_fields": ["carton_damage", "unit_damage", "quality_flags"],
        "reasoning_hint": "Inbound defect packaging violation claim.",
    },
    "unplanned_prep": {
        "primary_source": "prep",
        "secondary_sources": [],
        "prep_fields": ["polybag_present", "polybag_sealed", "fnsku_label_placement_valid", "manufacturer_barcode_covered"],
        "reasoning_hint": "Unplanned prep charge dispute.",
    },
    "lost_inbound": {
        "primary_source": "receiving",
        "secondary_sources": ["prep"],
        "receiving_fields": [
            "qty_ordered", "qty_received", "quantity_matches_po", "identity_matches_po", "identity_match", "carton_damage"
        ],
        "prep_fields": ["fba_shipment_id"],
        "reasoning_hint": (
            "A lost_inbound adjustment claims unit loss. Receiving record showing qty_received matching qty_ordered CONTRADICTS loss claim."
        ),
    },
    "warehouse_lost": {
        "primary_source": "receiving",
        "secondary_sources": ["prep"],
        "receiving_fields": ["qty_ordered", "qty_received", "quantity_matches_po"],
        "reasoning_hint": "Warehouse loss claim.",
    },
    "damaged_in_warehouse": {
        "primary_source": "receiving",
        "secondary_sources": ["prep", "returns"],
        "receiving_fields": ["carton_damage", "unit_damage", "unit_undamaged", "quality_flags", "identity_match"],
        "prep_fields": ["polybag_present_sealed"],
        "returns_fields": ["observed_state", "amazon_condition", "operator_disposition", "condition_grade"],
        "reasoning_hint": (
            "A damaged_in_warehouse claim means channel damaged our unit. Receiving showing unit_undamaged at receipt SUPPORTS reimbursement."
        ),
    },
    "warehouse_damaged": {
        "primary_source": "receiving",
        "secondary_sources": ["returns"],
        "receiving_fields": ["unit_undamaged", "unit_damage", "carton_damage"],
        "returns_fields": ["condition_grade", "observed_state"],
        "reasoning_hint": "Warehouse damage claim.",
    },
    "fulfilment_fee_weight_tier": {
        "primary_source": "receiving",
        "secondary_sources": ["prep"],
        "receiving_fields": [
            "cartons_ordered", "cartons_received", "units_per_carton_ordered",
            "units_per_carton_counted", "spec_colour", "spec_variant", "spec_components",
            "quality_flags", "sku", "asin", "product_title"
        ],
        "prep_fields": ["sku", "fnsku", "fba_shipment_id"],
        "reasoning_hint": (
            "Fulfilment fee weight tier charge overcharge dispute. "
            "Receiving spec fields (carton counts, units per carton, spec components) establish physical item attributes. "
            "If verified item specs contradict assigned weight tier → CONTRADICTED. If missing physical measurements → UNCERTAIN."
        ),
    },
    "refund_issued_item_not_returned": {
        "primary_source": "returns",
        "secondary_sources": ["pack"],
        "returns_fields": [
            "identity_matches_order", "completeness_verified", "condition_grade",
            "disposition_assigned", "identity_match", "observed_state", "amazon_condition", "operator_disposition"
        ],
        "pack_fields": ["all_items_present", "quantities_correct", "units_packed", "pack_status"],
        "reasoning_hint": (
            "Claims refund issued but unit not returned. A returns record showing disposition=restock or refurbish CONTRADICTS the charge."
        ),
    },
    "customer_return": {
        "primary_source": "returns",
        "secondary_sources": ["pack"],
        "returns_fields": ["identity_matches_order", "completeness_verified", "disposition_assigned"],
        "reasoning_hint": "Customer return item claim.",
    },
}

DEFAULT_ROUTING = {
    "primary_source": "receiving",
    "secondary_sources": [],
    "receiving_fields": ["qty_ordered", "qty_received", "unit_undamaged"],
    "reasoning_hint": "Default evidence routing for unclassified charge type.",
}


# ---------------------------------------------------------------------------
# Matching & Extraction
# ---------------------------------------------------------------------------

def _extract_fields(
    source_name: str,
    record: dict,
    field_names: list[str],
    relevance_note: str,
) -> list[EvidenceField]:
    result = []
    rid = record.get("record_id", f"{source_name}-unknown")
    ts = record.get("captured_at", "")
    for fn in field_names:
        val = record.get(fn, "")
        if val is not None and str(val) != "":
            result.append(EvidenceField(
                source=source_name,
                record_id=rid,
                field_name=fn,
                field_value=str(val),
                relevance_note=relevance_note,
                timestamp=ts,
            ))
    return result


def match_charge(
    charge: FeeCharge,
    upstream: UpstreamBundle | None,
) -> EvidenceBundle:
    """
    Match a single FeeCharge to its upstream evidence across Receiving, Prep, Pack, and Returns.
    """
    bundle = EvidenceBundle(
        charge=charge,
        unit_id=charge.unit_id or charge.fba_shipment_id or charge.order_id,
        upstream_found=upstream is not None,
        raw_upstream=upstream.as_dict() if upstream else {},
    )

    if upstream is None:
        bundle.missing_fields = ["all_upstream_records"]
        return bundle

    routing = CHARGE_ROUTING.get(charge.charge_type, DEFAULT_ROUTING)
    primary = routing.get("primary_source", "receiving")
    secondaries = routing.get("secondary_sources", [])

    source_map = {
        "prep": upstream.prep,
        "receiving": upstream.receiving,
        "pack": upstream.pack,
        "returns": upstream.returns,
    }

    # Primary fields
    p_fields = routing.get(f"{primary}_fields", [])
    for rec in source_map.get(primary, []):
        bundle.fields.extend(_extract_fields(
            primary, rec, p_fields, f"Primary evidence for {charge.charge_type}"
        ))

    # Secondary fields
    for sec in secondaries:
        s_fields = routing.get(f"{sec}_fields", [])
        for rec in source_map.get(sec, []):
            bundle.fields.extend(_extract_fields(
                sec, rec, s_fields, f"Secondary evidence for {charge.charge_type}"
            ))

    # Check temporal validity (evidence timestamp vs charge posted date)
    # Note: Customer returns naturally postdate the refund date, so exempt returns from postdate block
    if charge.posted_date and bundle.fields and charge.charge_type not in ("refund_issued_item_not_returned", "customer_return"):
        try:
            chg_dt = datetime.fromisoformat(charge.posted_date[:10])
            for f in bundle.fields:
                if f.timestamp:
                    evi_dt = datetime.fromisoformat(f.timestamp[:10])
                    if evi_dt > chg_dt:
                        bundle.evidence_postdates_charge = True
                        break
        except (ValueError, IndexError):
            pass

    # Check cross-manager conflicts (Section 2.4)
    # E.g. Receiving unit_undamaged=pass/none vs Returns observed_state=damaged
    rcv_clean = any(f.field_name in ("unit_undamaged", "carton_damage") and f.field_value in ("pass", "none", "yes") for f in bundle.fields if f.source == "receiving")
    rtn_damaged = any(f.field_name in ("observed_state", "unit_damage") and f.field_value in ("damaged", "defective") for f in bundle.fields if f.source == "returns")
    if rcv_clean and rtn_damaged:
        bundle.conflicts.append(EvidenceConflict(
            source_a="receiving",
            source_b="returns",
            record_a="RCV-clean",
            record_b="RTN-damaged",
            conflict_type="intake_vs_return_condition_discrepancy",
            description="Receiving record shows undamaged unit at intake, but Returns record shows unit arrived damaged post-sale."
        ))

    # Calculate evidence completeness gap score (Section 2.3)
    expected_count = max(len(p_fields), 1)
    found_count = len(bundle.fields)
    bundle.completeness_score = min(round(found_count / expected_count, 2), 1.0)
    bundle.missing_fields = [fn for fn in p_fields if not any(f.field_name == fn for f in bundle.fields)]

    return bundle


def detect_duplicates(
    charges: list[FeeCharge],
) -> dict[str, str]:
    """
    Section 1.2: Detect charges that appear to be duplicates.
    Same unit_id/shipment_id + charge_type + amount within 30 days.
    First charge is kept eligible; second gets flagged for DUPLICATE_SUPPRESSED.
    """
    from collections import defaultdict
    from datetime import date

    duplicates: dict[str, str] = {}
    groups: dict[tuple, list[FeeCharge]] = defaultdict(list)

    for c in charges:
        uid = c.unit_id or c.fba_shipment_id or c.order_id
        if uid and c.charge_type:
            groups[(uid, c.charge_type)].append(c)

    for key, group in groups.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda x: x.posted_date or "")
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if a.amount_usd == b.amount_usd and a.amount_usd > 0.0:
                    try:
                        da = date.fromisoformat(a.posted_date[:10])
                        db = date.fromisoformat(b.posted_date[:10])
                        if abs((da - db).days) <= 30:
                            duplicates[b.line_id] = f"DUPLICATE_SUPPRESSED: Duplicate of earlier charge {a.line_id} (same unit, charge type, amount ${a.amount_usd:.2f} within 30 days)"
                    except (ValueError, IndexError):
                        pass

    return duplicates
