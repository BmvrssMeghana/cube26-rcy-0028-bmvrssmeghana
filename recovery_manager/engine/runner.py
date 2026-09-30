"""
Recovery Manager — Main Engine
Orchestrates: ingest → match → classify → audit → report
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .ingestor import FeeCharge, UpstreamBundle, load_from_files, load_from_text
from .evidence_matcher import match_charge, detect_duplicates
from .sla_engine import compute_sla
from .classifier import classify, ClaimDecision


def _safe_asdict(obj) -> dict:
    try:
        return asdict(obj)
    except Exception:
        return vars(obj)


def run_recovery(
    charges: list[FeeCharge],
    upstream_index: dict[str, UpstreamBundle],
    org_id_filter: str | None = None,
) -> dict[str, Any]:
    """
    Core pipeline:
      1. Filter by org if requested (tenancy isolation)
      2. Detect duplicates
      3. For each charge: match evidence → compute SLA → classify
      4. Return structured results + summary metrics
    """

    # --- Tenancy isolation ---
    if org_id_filter:
        charges = [c for c in charges if c.org_id == org_id_filter]
        upstream_index = {
            uid: bundle
            for uid, bundle in upstream_index.items()
            if bundle.org_id == org_id_filter
        }

    # --- Duplicate detection ---
    dup_map = detect_duplicates(charges)

    # --- Per-charge processing ---
    decisions: list[ClaimDecision] = []
    for charge in charges:
        upstream = upstream_index.get(charge.unit_id)

        # --- Evidence match ---
        try:
            bundle = match_charge(charge, upstream)
        except Exception as e:
            # Fail-open: preserve charge, move to review
            decisions.append(ClaimDecision(
                line_id=charge.line_id,
                unit_id=charge.unit_id,
                org_id=charge.org_id,
                charge_type=charge.charge_type,
                amount_usd=charge.amount_usd,
                verdict="PENDING_REVIEW",
                claim_amount=0.0,
                reasoning=f"Evidence matching failed: {e}",
                error=str(e),
            ))
            continue

        # --- SLA ---
        sla = compute_sla(charge.charge_type, charge.posted_date)

        # --- Classify ---
        try:
            decision = classify(bundle, sla, dup_map.get(charge.line_id, ""))
        except Exception as e:
            decisions.append(ClaimDecision(
                line_id=charge.line_id,
                unit_id=charge.unit_id,
                org_id=charge.org_id,
                charge_type=charge.charge_type,
                amount_usd=charge.amount_usd,
                verdict="PENDING_REVIEW",
                claim_amount=0.0,
                reasoning=f"Classification failed: {e}",
                error=str(e),
            ))
            continue

        decisions.append(decision)

    # --- Summary metrics ---
    total = len(decisions)
    recommended = [d for d in decisions if d.verdict == "CONTRADICTED"]
    supported = [d for d in decisions if d.verdict == "SUPPORTED"]
    silent = [d for d in decisions if d.verdict == "SILENT"]
    uncertain = [d for d in decisions if d.verdict == "UNCERTAIN"]
    pending = [d for d in decisions if d.verdict == "PENDING_REVIEW"]
    duplicates_found = [d for d in decisions if d.duplicate_flag]

    total_claim_value = sum(d.claim_amount for d in recommended)

    metrics = {
        "total_charges_evaluated": total,
        "claims_recommended": len(recommended),
        "supported_charges": len(supported),
        "silent_charges": len(silent),
        "uncertain_review_rate": len(uncertain),
        "pending_review": len(pending),
        "duplicate_flags": len(duplicates_found),
        "total_claim_value_usd": round(total_claim_value, 2),
    }

    results = {
        "metrics": metrics,
        "decisions": [_safe_asdict(d) for d in decisions],
    }

    try:
        from ..db.database import save_claim_audit_logs
        save_claim_audit_logs(results["decisions"])
    except Exception as e:
        print(f"[Warning] Failed to persist audit log: {e}")

    return results


def run_from_files(
    fee_path: Path | None = None,
    receiving_path: Path | None = None,
    prep_path: Path | None = None,
    pack_path: Path | None = None,
    returns_path: Path | None = None,
    org_id_filter: str | None = None,
) -> dict[str, Any]:
    charges, upstream_index = load_from_files(
        fee_path, receiving_path, prep_path, pack_path, returns_path
    )
    return run_recovery(charges, upstream_index, org_id_filter)


def run_from_text(
    fee_text: str,
    receiving_text: str = "",
    prep_text: str = "",
    pack_text: str = "",
    returns_text: str = "",
    org_id_filter: str | None = None,
) -> dict[str, Any]:
    charges, upstream_index = load_from_text(
        fee_text, receiving_text, prep_text, pack_text, returns_text
    )
    return run_recovery(charges, upstream_index, org_id_filter)
