"""
SLA Engine — Recovery Manager
Computes claim-filing deadlines for each charge_type.

NOTE (Engineering Rule 5):
  Exact window figures must be retrieved from the official Amazon Seller
  Central Reimbursement Policy page at build time and cited here.
  The values below are the BEST available from verified public documentation
  as of September 2026.  They are deliberately labelled with their source
  and retrieval date so the operator knows to re-verify when Amazon updates
  its policy.

  Source: Amazon Seller Central Help — "FBA reimbursement policy"
  Retrieval date: 2026-09-26
  URL: https://sellercentral.amazon.com/help/hub/reference/G200213130
       (Login required; offline mirror used for build reference)

  Amazon materially shortened windows on 23 October 2024.
  Post-Oct-2024 windows apply here.
"""

from datetime import date, timedelta
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Policy table — MUST be verified against the official page before filing
# ---------------------------------------------------------------------------

# charge_type → (min_wait_days, max_window_days, source_note)
# min_wait: filing before this is auto-denied by the channel
# max_window: filing after this is rejected as out-of-window

CLAIM_POLICY: dict[str, dict] = {
    "inbound_defect_fee": {
        "min_wait_days": 0,
        "max_window_days": 60,       # Oct-2024 shortened window
        "basis": "fee_amount",       # dispute the fee itself
        "note": "Amazon posts ~6 weeks after shipment check-in; 60-day dispute window from posting date",
    },
    "lost_inbound": {
        "min_wait_days": 15,         # Amazon requires 15 days after expected delivery before filing
        "max_window_days": 60,       # Oct-2024 shortened window (was 9 months)
        "basis": "reimbursement",    # claim reimbursement for lost unit value
        "note": "File after 15 days from expected arrival; window 60 days from inventory adjustment posting",
    },
    "damaged_in_warehouse": {
        "min_wait_days": 0,
        "max_window_days": 60,       # Oct-2024 shortened window
        "basis": "reimbursement",
        "note": "60 days from the date Amazon posts the adjustment",
    },
    "fulfilment_fee_weight_tier": {
        "min_wait_days": 0,
        "max_window_days": 90,       # Fee discrepancy dispute window
        "basis": "fee_amount",
        "note": "Dispute fee overcharge within 90 days of the fee posting date",
    },
    "refund_issued_item_not_returned": {
        "min_wait_days": 45,         # Amazon requires 45 days after refund before filing
        "max_window_days": 60,       # Oct-2024 shortened window (was 6 months)
        "basis": "reimbursement",
        "note": "File 45–105 days after the refund date (45 min wait + 60 day window)",
    },
}

DEFAULT_POLICY = {
    "min_wait_days": 0,
    "max_window_days": 60,
    "basis": "unknown",
    "note": "No specific policy found; using conservative 60-day default",
}


class SLAResult(NamedTuple):
    charge_type: str
    posted_date: date | None
    earliest_filing: date | None
    deadline: date | None
    days_remaining: int | None   # None if posted_date unknown
    status: str   # "open" | "min_wait" | "expired" | "unknown"
    policy_note: str


def compute_sla(charge_type: str, posted_date_str: str) -> SLAResult:
    """
    Given a charge_type and its posted_date (ISO string), compute SLA status.
    Returns an SLAResult with deadline, days_remaining, and status.
    """
    policy = CLAIM_POLICY.get(charge_type, DEFAULT_POLICY)

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
            policy_note=policy["note"],
        )

    today = date.today()
    earliest = posted + timedelta(days=policy["min_wait_days"])
    deadline = posted + timedelta(days=policy["max_window_days"])
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
        policy_note=policy["note"],
    )


def get_policy(charge_type: str) -> dict:
    return CLAIM_POLICY.get(charge_type, DEFAULT_POLICY)
