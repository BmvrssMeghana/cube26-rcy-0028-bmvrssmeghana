"""
Evaluation Script — Recovery Manager
Runs the pipeline against a self-constructed eval set with known ground truth,
then reports Claim Precision and other metrics.

Ground-truth labels are deliberately planted (see eval_dataset.py).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recovery_manager.engine.runner import run_from_text
from eval.eval_dataset import EVAL_FEE_CSV, EVAL_RECEIVING_CSV, EVAL_PREP_CSV, EVAL_RETURNS_CSV, GROUND_TRUTH


def run_eval() -> dict:
    result = run_from_text(
        fee_text=EVAL_FEE_CSV,
        receiving_text=EVAL_RECEIVING_CSV,
        prep_text=EVAL_PREP_CSV,
        returns_text=EVAL_RETURNS_CSV,
    )

    decisions = result["decisions"]

    total = len(decisions)
    recommended_ids = {d["line_id"] for d in decisions if d["verdict"] == "CONTRADICTED"}
    all_ids = {d["line_id"] for d in decisions}

    # Evaluate against ground truth
    correctly_supported = 0
    incorrectly_recommended = 0
    missed_recoverable = 0
    uncertain_count = sum(1 for d in decisions if d["verdict"] in ("UNCERTAIN", "PENDING_REVIEW"))

    failure_modes: list[dict] = []

    for line_id, truth in GROUND_TRUTH.items():
        predicted_verdict = next(
            (d["verdict"] for d in decisions if d["line_id"] == line_id), None
        )
        predicted_claim = next(
            (d for d in decisions if d["line_id"] == line_id), None
        )

        if truth["expected_verdict"] == "CONTRADICTED":
            if predicted_verdict == "CONTRADICTED":
                correctly_supported += 1
            else:
                missed_recoverable += 1
                failure_modes.append({
                    "line_id": line_id,
                    "mode": "missed_recoverable",
                    "expected": "CONTRADICTED",
                    "got": predicted_verdict,
                    "note": truth.get("note", ""),
                })
        else:
            if predicted_verdict == "CONTRADICTED":
                incorrectly_recommended += 1
                failure_modes.append({
                    "line_id": line_id,
                    "mode": "false_claim",
                    "expected": truth["expected_verdict"],
                    "got": predicted_verdict,
                    "note": truth.get("note", ""),
                })

    claims_recommended = len(recommended_ids)
    precision = (correctly_supported / claims_recommended) if claims_recommended > 0 else 0.0

    report = {
        "eval_summary": {
            "total_charges_evaluated": total,
            "ground_truth_cases": len(GROUND_TRUTH),
            "claims_recommended": claims_recommended,
            "correctly_supported_claims": correctly_supported,
            "incorrectly_recommended_claims": incorrectly_recommended,
            "missed_recoverable_claims": missed_recoverable,
            "uncertain_review_rate": uncertain_count,
            "claim_precision": round(precision, 4),
        },
        "failure_modes": failure_modes,
        "all_decisions": decisions,
    }

    return report


if __name__ == "__main__":
    report = run_eval()
    summary = report["eval_summary"]
    print("\n========== RECOVERY MANAGER — EVAL REPORT ==========")
    print(f"  Total charges evaluated : {summary['total_charges_evaluated']}")
    print(f"  Claims recommended      : {summary['claims_recommended']}")
    print(f"  Correctly supported     : {summary['correctly_supported_claims']}")
    print(f"  Incorrectly recommended : {summary['incorrectly_recommended_claims']}")
    print(f"  Missed recoverable      : {summary['missed_recoverable_claims']}")
    print(f"  Uncertain / review rate : {summary['uncertain_review_rate']}")
    print(f"  CLAIM PRECISION         : {summary['claim_precision']:.2%}")
    print("\n--- Failure Modes ---")
    for fm in report["failure_modes"]:
        print(f"  [{fm['mode']}] {fm['line_id']}: expected {fm['expected']}, got {fm['got']} — {fm['note']}")
    print("=====================================================\n")

    # Save full report
    out_path = Path(__file__).parent / "eval_report.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Full report saved to: {out_path}")
