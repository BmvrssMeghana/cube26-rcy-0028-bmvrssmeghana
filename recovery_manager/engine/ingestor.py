"""
Ingestor — Recovery Manager
Loads fee/reimbursement report and all four upstream evidence sources.
Normalises columns and builds a keyed index for join operations.
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
    line_id: str
    report_type: str
    unit_id: str
    org_id: str
    sku: str
    fnsku: str
    fba_shipment_id: str
    order_id: str
    charge_type: str
    quantity: int
    amount_usd: float
    posted_date: str   # ISO date string


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

def parse_fee_report(rows: list[dict]) -> list[FeeCharge]:
    charges = []
    for r in rows:
        if not r.get("line_id"):
            continue
        try:
            qty = int(r.get("quantity", 1) or 1)
        except ValueError:
            qty = 1
        try:
            amt = float(r.get("amount_usd", 0.0) or 0.0)
        except ValueError:
            amt = 0.0
        charges.append(FeeCharge(
            line_id=r.get("line_id", ""),
            report_type=r.get("report_type", ""),
            unit_id=r.get("unit_id", ""),
            org_id=r.get("org_id", ""),
            sku=r.get("sku", ""),
            fnsku=r.get("fnsku", ""),
            fba_shipment_id=r.get("fba_shipment_id", ""),
            order_id=r.get("order_id", ""),
            charge_type=r.get("charge_type", ""),
            quantity=qty,
            amount_usd=amt,
            posted_date=r.get("posted_date", ""),
        ))
    return charges


def build_upstream_index(
    receiving_rows: list[dict],
    prep_rows: list[dict],
    pack_rows: list[dict],
    returns_rows: list[dict],
) -> dict[str, UpstreamBundle]:
    """Build a unit_id → UpstreamBundle map."""
    index: dict[str, UpstreamBundle] = {}

    def _ensure(uid: str, org: str) -> UpstreamBundle:
        if uid not in index:
            index[uid] = UpstreamBundle(unit_id=uid, org_id=org)
        return index[uid]

    for r in receiving_rows:
        uid = r.get("unit_id", "")
        if uid:
            _ensure(uid, r.get("org_id", "")).receiving.append(r)

    for r in prep_rows:
        uid = r.get("unit_id", "")
        if uid:
            _ensure(uid, r.get("org_id", "")).prep.append(r)

    for r in pack_rows:
        uid = r.get("unit_id", "")
        if uid:
            _ensure(uid, r.get("org_id", "")).pack.append(r)

    for r in returns_rows:
        uid = r.get("unit_id", "")
        if uid:
            _ensure(uid, r.get("org_id", "")).returns.append(r)

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
) -> tuple[list[FeeCharge], dict[str, UpstreamBundle]]:
    """Load everything from disk and return charges + upstream index."""
    fee_rows = _load_csv(fee_path or DATA_DIR / "fee_report_sample.csv")
    rcv_rows = _load_csv(receiving_path or UPSTREAM_DIR / "receiving_sample.csv")
    prp_rows = _load_csv(prep_path or UPSTREAM_DIR / "prep_sample.csv")
    pck_rows = _load_csv(pack_path or UPSTREAM_DIR / "pack_sample.csv")
    rtn_rows = _load_csv(returns_path or UPSTREAM_DIR / "returns_sample.csv")

    charges = parse_fee_report(fee_rows)
    upstream_index = build_upstream_index(rcv_rows, prp_rows, pck_rows, rtn_rows)
    return charges, upstream_index


def load_from_text(
    fee_text: str,
    receiving_text: str = "",
    prep_text: str = "",
    pack_text: str = "",
    returns_text: str = "",
) -> tuple[list[FeeCharge], dict[str, UpstreamBundle]]:
    """Parse from in-memory CSV strings (used by the API upload endpoint)."""
    fee_rows = _load_csv_from_text(fee_text) if fee_text else []
    rcv_rows = _load_csv_from_text(receiving_text) if receiving_text else []
    prp_rows = _load_csv_from_text(prep_text) if prep_text else []
    pck_rows = _load_csv_from_text(pack_text) if pack_text else []
    rtn_rows = _load_csv_from_text(returns_text) if returns_text else []

    charges = parse_fee_report(fee_rows)
    upstream_index = build_upstream_index(rcv_rows, prp_rows, pck_rows, rtn_rows)
    return charges, upstream_index
