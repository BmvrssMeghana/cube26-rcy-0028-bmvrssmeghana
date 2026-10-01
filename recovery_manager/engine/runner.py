"""
Recovery Manager — Main Engine & Agent Orchestrator
Orchestrates: Ingest → Entity Resolution → Policy Time Machine → Retrieval → Verification → Contradiction Resolution → Classification → Reimbursement Netting → Claim Building → Monotonic Audit.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .ingestor import FeeCharge, ReimbursementRecord, UpstreamBundle, load_from_files, load_from_text
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
    reimbursements: list[ReimbursementRecord] | None = None,
    upstream_index: dict[str, UpstreamBundle] | None = None,
    org_id_filter: str | None = None,
) -> dict[str, Any]:
    """
    Core 10-Agent Pipeline execution.
    """
    reimbursements = reimbursements or []
    upstream_index = upstream_index or {}

    # 1. Tenancy Isolation
    if org_id_filter:
        charges = [c for c in charges if c.org_id == org_id_filter]
        upstream_index = {
            uid: bundle
            for uid, bundle in upstream_index.items()
            if bundle.org_id == org_id_filter
        }

    # 2. Duplicate Detection (Section 1.2)
    dup_map = detect_duplicates(charges)

    # 3. Per-charge processing
    decisions: list[ClaimDecision] = []
    run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    for charge in charges:
        # Multi-entity resolution lookup (unit_id, shipment_id, order_id, sku)
        lookup_keys = [charge.unit_id, charge.fba_shipment_id, charge.order_id, charge.sku]
        upstream = None
        for k in lookup_keys:
            if k and k in upstream_index:
                upstream = upstream_index[k]
                break

        # Evidence Matcher & Planner
        try:
            bundle = match_charge(charge, upstream)
        except Exception as e:
            decisions.append(ClaimDecision(
                line_id=charge.line_id,
                unit_id=charge.unit_id or charge.fba_shipment_id or charge.order_id,
                org_id=charge.org_id,
                charge_type=charge.charge_type,
                amount_usd=charge.amount_usd,
                verdict="PENDING_REVIEW",
                claim_amount=0.0,
                reasoning=f"Evidence matching failed: {e}",
                error=str(e),
            ))
            continue

        # Policy Time Machine SLA
        sla = compute_sla(charge.charge_type, charge.posted_date)

        # Classification & Monotonic Auditor
        try:
            decision = classify(bundle, sla, reimbursements, dup_map.get(charge.line_id, ""))
        except Exception as e:
            decisions.append(ClaimDecision(
                line_id=charge.line_id,
                unit_id=charge.unit_id or charge.fba_shipment_id or charge.order_id,
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

    # 4. Summary Metrics & Root Cause Analysis
    total = len(decisions)
    recommended = [d for d in decisions if d.verdict == "CONTRADICTED"]
    supported = [d for d in decisions if d.verdict == "SUPPORTED"]
    silent = [d for d in decisions if d.verdict == "SILENT"]
    uncertain = [d for d in decisions if d.verdict == "UNCERTAIN"]
    not_yet = [d for d in decisions if d.verdict == "NOT_YET_SUPPORTED"]
    dup_suppressed = [d for d in decisions if d.verdict == "DUPLICATE_SUPPRESSED"]
    already_recovered = [d for d in decisions if d.verdict == "ALREADY_RECOVERED"]
    expired = [d for d in decisions if d.verdict == "EXPIRED"]
    pending = [d for d in decisions if d.verdict == "PENDING_REVIEW"]

    total_claim_value = sum(d.claim_amount for d in recommended)

    # Root Cause Driver Breakdown (USP #10)
    root_cause_counts = {}
    for d in decisions:
        driver = getattr(d, "root_cause_driver", "General Dispute")
        root_cause_counts[driver] = root_cause_counts.get(driver, 0) + 1

    top_root_cause = max(root_cause_counts.items(), key=lambda x: x[1])[0] if root_cause_counts else "None"

    metrics = {
        "analysis_run_timestamp": run_timestamp,
        "total_charges_evaluated": total,
        "claims_recommended": len(recommended),
        "supported_charges": len(supported),
        "silent_charges": len(silent),
        "uncertain_review_rate": len(uncertain),
        "not_yet_supported": len(not_yet),
        "duplicate_suppressed": len(dup_suppressed),
        "already_recovered": len(already_recovered),
        "expired_claims": len(expired),
        "pending_review": len(pending),
        "total_claim_value_usd": round(total_claim_value, 2),
        "top_root_cause_driver": top_root_cause,
        "root_cause_breakdown": root_cause_counts,
    }

    # Run-to-Run Delta Calculation (USP #9)
    global _LAST_RUN_RESULTS
    delta = {"new_claims": 0, "value_delta_usd": 0.0}
    if _LAST_RUN_RESULTS:
        prev_val = _LAST_RUN_RESULTS.get("metrics", {}).get("total_claim_value_usd", 0.0)
        prev_claims = _LAST_RUN_RESULTS.get("metrics", {}).get("claims_recommended", 0)
        delta = {
            "new_claims": len(recommended) - prev_claims,
            "value_delta_usd": round(total_claim_value - prev_val, 2),
        }

    results = {
        "metrics": metrics,
        "delta": delta,
        "decisions": [_safe_asdict(d) for d in decisions],
    }

    _LAST_RUN_RESULTS = results

    # Save to PostgreSQL database
    try:
        from ..db.database import save_claim_audit_logs
        save_claim_audit_logs(results["decisions"])
    except Exception as e:
        print(f"[Warning] Failed to persist audit log to DB: {e}")

    return results

_LAST_RUN_RESULTS: dict[str, Any] | None = None


def run_from_files(
    fee_path: Path | None = None,
    receiving_path: Path | None = None,
    prep_path: Path | None = None,
    pack_path: Path | None = None,
    returns_path: Path | None = None,
    org_id_filter: str | None = None,
) -> dict[str, Any]:
    charges, reimbursements, upstream_index = load_from_files(
        fee_path, receiving_path, prep_path, pack_path, returns_path
    )
    return run_recovery(charges, reimbursements, upstream_index, org_id_filter)


def run_from_text(
    fee_text: str,
    receiving_text: str = "",
    prep_text: str = "",
    pack_text: str = "",
    returns_text: str = "",
    org_id_filter: str | None = None,
) -> dict[str, Any]:
    charges, reimbursements, upstream_index = load_from_text(
        fee_text, receiving_text, prep_text, pack_text, returns_text
    )
    return run_recovery(charges, reimbursements, upstream_index, org_id_filter)
