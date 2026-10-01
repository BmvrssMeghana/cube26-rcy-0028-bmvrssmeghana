"""
SLA Engine & Policy Agent — Recovery Manager
Computes claim-filing deadlines for each charge_type with versioned historical policies.

Policy Time Machine (Section 2.1):
  Applies the policy version in effect when the charge posted (effective_from <= posted_date < effective_to).
"""

from datetime import date, timedelta
from typing import NamedTuple, Any

VERSIONED_POLICIES: list[dict[str, Any]] = [
    # --- Pre-Oct 2024 Policy Version (V1) ---
    {
        "version": "V1-Legacy",
        "effective_from": "2020-01-01",
        "effective_to": "2024-10-22",
        "source_url": "https://sellercentral.amazon.com/help/hub/reference/G200213130?v=v1",
        "policies": {
            "inbound_defect_fee": {"min_wait_days": 0, "max_window_days": 90, "basis": "fee_amount", "note": "V1 Policy: 90-day dispute window"},
            "lost_inbound": {"min_wait_days": 15, "max_window_days": 270, "basis": "reimbursement", "note": "V1 Policy: 9-month filing window"},
            "damaged_in_warehouse": {"min_wait_days": 0, "max_window_days": 180, "basis": "reimbursement", "note": "V1 Policy: 180-day window"},
            "fulfilment_fee_weight_tier": {"min_wait_days": 0, "max_window_days": 120, "basis": "fee_amount", "note": "V1 Policy: 120-day weight dispute window"},
            "refund_issued_item_not_returned": {"min_wait_days": 45, "max_window_days": 180, "basis": "reimbursement", "note": "V1 Policy: 6-month window"},
        }
    },
    # --- Post-Oct 2024 Policy Version (V2 - Current) ---
    {
        "version": "V2-Current",
        "effective_from": "2024-10-23",
        "effective_to": "2099-12-31",
        "source_url": "https://sellercentral.amazon.com/help/hub/reference/G200213130",
        "policies": {
            "inbound_defect_fee": {"min_wait_days": 0, "max_window_days": 60, "basis": "fee_amount", "note": "Oct-2024 Policy: Shortened 60-day dispute window"},
            "lost_inbound": {"min_wait_days": 15, "max_window_days": 60, "basis": "reimbursement", "note": "Oct-2024 Policy: Shortened 60-day window from inventory adjustment"},
            "damaged_in_warehouse": {"min_wait_days": 0, "max_window_days": 60, "basis": "reimbursement", "note": "Oct-2024 Policy: 60-day window"},
            "fulfilment_fee_weight_tier": {"min_wait_days": 0, "max_window_days": 90, "basis": "fee_amount", "note": "Fee discrepancy dispute window: 90 days"},
            "refund_issued_item_not_returned": {"min_wait_days": 45, "max_window_days": 105, "basis": "reimbursement", "note": "Oct-2024 Policy: 45 min wait + 60 day window (105 days total from refund date)"},
        }
    }
]

DEFAULT_POLICY = {
    "version": "V2-Current",
    "min_wait_days": 0,
    "max_window_days": 60,
    "basis": "unknown",
    "note": "Default 60-day policy",
}


class SLAResult(NamedTuple):
    charge_type: str
    posted_date: date | None
    earliest_filing: date | None
    deadline: date | None
    days_remaining: int | None
    status: str   # "open" | "min_wait" | "expired" | "unknown"
    policy_note: str
    policy_version: str


def get_versioned_policy(charge_type: str, posted_date_str: str) -> tuple[dict, str]:
    """Select the policy version active on the charge's posted date."""
    posted_iso = posted_date_str[:10] if posted_date_str else "2099-12-31"
    
    for v in VERSIONED_POLICIES:
        if v["effective_from"] <= posted_iso <= v["effective_to"]:
            pol = v["policies"].get(charge_type, DEFAULT_POLICY)
            return pol, v["version"]
            
    # Fallback to current
    current_v = VERSIONED_POLICIES[-1]
    return current_v["policies"].get(charge_type, DEFAULT_POLICY), current_v["version"]


def compute_sla(charge_type: str, posted_date_str: str) -> SLAResult:
    """Compute SLA status using Policy Time Machine."""
    policy, p_version = get_versioned_policy(charge_type, posted_date_str)

    posted: date | None = None
    if posted_date_str:
        try:
            posted = date.fromisoformat(posted_date_str[:10])
        except ValueError:
            pass

    if posted is None:
        return SLAResult(
            charge_type=charge_type,
            posted_date=None,
            earliest_filing=None,
            deadline=None,
            days_remaining=None,
            status="unknown",
            policy_note=policy.get("note", ""),
            policy_version=p_version,
        )

    today = date.today()
    earliest = posted + timedelta(days=policy.get("min_wait_days", 0))
    deadline = posted + timedelta(days=policy.get("max_window_days", 60))
    days_remaining = (deadline - today).days

    if today < earliest:
        status = "min_wait"
    elif today > deadline:
        status = "expired"
    else:
        status = "open"

    return SLAResult(
        charge_type=charge_type,
        posted_date=posted,
        earliest_filing=earliest,
        deadline=deadline,
        days_remaining=days_remaining,
        status=status,
        policy_note=f"[{p_version}] {policy.get('note', '')}",
        policy_version=p_version,
    )


def get_policy(charge_type: str) -> dict:
    return VERSIONED_POLICIES[-1]["policies"].get(charge_type, DEFAULT_POLICY)
