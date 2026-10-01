"""
Ingestor — Recovery Manager
Loads fee/reimbursement report and all four upstream evidence sources.
Normalises columns and builds a keyed index for multi-granularity join operations.
"""

import csv
import io
import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
UPSTREAM_DIR = DATA_DIR / "upstream"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class FeeCharge:
    line_id: str               # charge_id
    report_type: str           # fee_report | inventory_adjustment | reimbursement
    unit_id: str
    org_id: str
    sku: str
    fnsku: str
    fba_shipment_id: str       # shipment_id
    order_id: str              # amazon_order_id
    charge_type: str
    charge_subtype: str = ""
    granularity: str = "unit"  # unit | shipment | order
    quantity: int = 1
    amount_usd: float = 0.0    # amount_total
    posted_date: str = ""      # charged_at
    asin: str = ""
    description: str = ""


@dataclass
class ReimbursementRecord:
    reimbursement_id: str
    case_id: str | None
    approval_date: str
    amazon_order_id: str | None
    sku: str | None
    fnsku: str | None
    asin: str | None
    reason: str
    condition: str | None
    currency: str
    amount_per_unit: float
    amount_total: float
    quantity_reimbursed_cash: int
    quantity_reimbursed_inventory: int
    original_reimbursement_id: str | None


@dataclass
class UpstreamBundle:
    unit_id: str
    org_id: str
    receiving: list[dict] = field(default_factory=list)
    prep: list[dict] = field(default_factory=list)
    pack: list[dict] = field(default_factory=list)
    returns: list[dict] = field(default_factory=list)

    def as_dict(self):
        return asdict(self)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def _load_csv(path: Path | str) -> list[dict]:
    """Load a CSV file and return a list of dicts with stripped keys."""
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    with open(p, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append({k.strip(): v.strip() for k, v in row.items()})
    return rows


def _load_csv_from_text(text: str) -> list[dict]:
    """Parse CSV from an in-memory string."""
    reader = csv.DictReader(io.StringIO(text))
    return [{k.strip(): v.strip() for k, v in row.items()} for row in reader]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_fee_report(rows: list[dict]) -> tuple[list[FeeCharge], list[ReimbursementRecord]]:
    charges: list[FeeCharge] = []
    reimbursements: list[ReimbursementRecord] = []

    for r in rows:
        report_type = r.get("report_type", "fee_report")
        
        # Parse reimbursements schema A if present
        if report_type == "reimbursement" or r.get("reimbursement_id"):
            try:
                amt_tot = float(r.get("amount_total", r.get("amount_usd", 0.0)) or 0.0)
            except ValueError:
                amt_tot = 0.0
            reimbursements.append(ReimbursementRecord(
                reimbursement_id=r.get("reimbursement_id", r.get("line_id", "")),
                case_id=r.get("case_id"),
                approval_date=r.get("approval_date", r.get("posted_date", "")),
                amazon_order_id=r.get("amazon_order_id", r.get("order_id")),
                sku=r.get("sku"),
                fnsku=r.get("fnsku"),
                asin=r.get("asin"),
                reason=r.get("reason", r.get("charge_type", "reimbursement")),
                condition=r.get("condition"),
                currency=r.get("currency", "USD"),
                amount_per_unit=float(r.get("amount_per_unit", amt_tot) or 0.0),
                amount_total=amt_tot,
                quantity_reimbursed_cash=int(r.get("quantity_reimbursed_cash", 1) or 1),
                quantity_reimbursed_inventory=int(r.get("quantity_reimbursed_inventory", 0) or 0),
                original_reimbursement_id=r.get("original_reimbursement_id"),
            ))
            continue

        # Parse charges schema B
        line_id = r.get("line_id", r.get("charge_id", ""))
        if not line_id:
            continue

        try:
            qty = int(r.get("quantity", 1) or 1)
        except ValueError:
            qty = 1
        try:
            amt = float(r.get("amount_usd", r.get("amount_total", 0.0)) or 0.0)
        except ValueError:
            amt = 0.0

        granularity = r.get("granularity", "unit")
        if not granularity:
            if r.get("fba_shipment_id") and not r.get("unit_id"):
                granularity = "shipment"
            elif r.get("order_id") and not r.get("unit_id"):
                granularity = "order"
            else:
                granularity = "unit"

        charges.append(FeeCharge(
            line_id=line_id,
            report_type=report_type,
            unit_id=r.get("unit_id", ""),
            org_id=r.get("org_id", ""),
            sku=r.get("sku", ""),
            fnsku=r.get("fnsku", ""),
            fba_shipment_id=r.get("fba_shipment_id", r.get("shipment_id", "")),
            order_id=r.get("order_id", r.get("amazon_order_id", "")),
            charge_type=r.get("charge_type", ""),
            charge_subtype=r.get("charge_subtype", ""),
            granularity=granularity,
            quantity=qty,
            amount_usd=amt,
            posted_date=r.get("posted_date", r.get("charged_at", "")),
            asin=r.get("asin", ""),
            description=r.get("description", ""),
        ))

    return charges, reimbursements


def build_upstream_index(
    receiving_rows: list[dict],
    prep_rows: list[dict],
    pack_rows: list[dict],
    returns_rows: list[dict],
) -> dict[str, UpstreamBundle]:
    """
    Build a multi-key index mapping unit_id, shipment_id, order_id, or sku → UpstreamBundle.
    """
    index: dict[str, UpstreamBundle] = {}

    def _ensure(key: str, org: str) -> UpstreamBundle:
        if key not in index:
            index[key] = UpstreamBundle(unit_id=key, org_id=org)
        return index[key]

    for r in receiving_rows:
        keys = filter(None, [r.get("unit_id"), r.get("fba_shipment_id"), r.get("shipment_id"), r.get("po_number"), r.get("sku")])
        for k in keys:
            _ensure(k, r.get("org_id", "")).receiving.append(r)

    for r in prep_rows:
        keys = filter(None, [r.get("unit_id"), r.get("fba_shipment_id"), r.get("shipment_id"), r.get("work_order_id"), r.get("sku")])
        for k in keys:
            _ensure(k, r.get("org_id", "")).prep.append(r)

    for r in pack_rows:
        keys = filter(None, [r.get("unit_id"), r.get("outbound_shipment_id"), r.get("order_id"), r.get("sku")])
        for k in keys:
            _ensure(k, r.get("org_id", "")).pack.append(r)

    for r in returns_rows:
        keys = filter(None, [r.get("unit_id"), r.get("order_id"), r.get("ordered_sku"), r.get("sku")])
        for k in keys:
            _ensure(k, r.get("org_id", "")).returns.append(r)

    return index


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_from_files(
    fee_path: Path | None = None,
    receiving_path: Path | None = None,
    prep_path: Path | None = None,
    pack_path: Path | None = None,
    returns_path: Path | None = None,
) -> tuple[list[FeeCharge], list[ReimbursementRecord], dict[str, UpstreamBundle]]:
    """Load everything from disk and return charges + reimbursements + upstream index."""
    fee_rows = _load_csv(fee_path or DATA_DIR / "fee_report_sample.csv")
    rcv_rows = _load_csv(receiving_path or UPSTREAM_DIR / "receiving_sample.csv")
    prp_rows = _load_csv(prep_path or UPSTREAM_DIR / "prep_sample.csv")
    pck_rows = _load_csv(pack_path or UPSTREAM_DIR / "pack_sample.csv")
    rtn_rows = _load_csv(returns_path or UPSTREAM_DIR / "returns_sample.csv")

    charges, reimbursements = parse_fee_report(fee_rows)
    upstream_index = build_upstream_index(rcv_rows, prp_rows, pck_rows, rtn_rows)
    return charges, reimbursements, upstream_index


def load_from_text(
    fee_text: str,
    receiving_text: str = "",
    prep_text: str = "",
    pack_text: str = "",
    returns_text: str = "",
) -> tuple[list[FeeCharge], list[ReimbursementRecord], dict[str, UpstreamBundle]]:
    """Parse from in-memory CSV strings."""
    fee_rows = _load_csv_from_text(fee_text) if fee_text else []
    rcv_rows = _load_csv_from_text(receiving_text) if receiving_text else []
    prp_rows = _load_csv_from_text(prep_text) if prep_text else []
    pck_rows = _load_csv_from_text(pack_text) if pack_text else []
    rtn_rows = _load_csv_from_text(returns_text) if returns_text else []

    charges, reimbursements = parse_fee_report(fee_rows)
    upstream_index = build_upstream_index(rcv_rows, prp_rows, pck_rows, rtn_rows)
    return charges, reimbursements, upstream_index
