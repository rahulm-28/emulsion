"""Plan limits. Stubbed — the check runs, and currently always passes.

ponytail: no quota is enforced. This exists as a real call site on the one path that
spends money, so M8 is "make this function return False sometimes" rather than "find
every place a job is created and add a check". The shape of the answer is already
correct: a decision plus a reason the user can read.

What M8 has to add, and nothing else:
  * a spend rollup per user per period (jobs already carry cost_usd)
  * a plans table, or a plan column that means something
  * a real implementation of `check`
"""

from __future__ import annotations

from dataclasses import dataclass

from emulsion_db import User

# Named so the stub is obvious in a stack trace and a log line.
UNLIMITED = float("inf")

PLAN_LIMITS: dict[str, float] = {
    # ponytail: every plan is unlimited until metering exists. Filling these in without
    # a spend rollup would reject nobody and reassure everybody, which is worse than
    # admitting the check is a stub.
    "free": UNLIMITED,
    "pro": UNLIMITED,
}


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    reason: str = ""
    limit_usd: float = UNLIMITED
    spent_usd: float = 0.0

    @property
    def is_stub(self) -> bool:
        return self.limit_usd == UNLIMITED


def limit_for(user: User) -> float:
    """The user's cap, honouring a per-account override before the plan default."""
    if user.monthly_cost_cap_usd is not None:
        return float(user.monthly_cost_cap_usd)
    return PLAN_LIMITS.get(user.plan, UNLIMITED)


def check(user: User, *, spent_usd: float = 0.0) -> QuotaDecision:
    """Whether this user may start another paid job.

    Always allows today. Called on the real path so the wiring is proven before the
    policy exists.
    """
    limit = limit_for(user)
    if limit == UNLIMITED:
        return QuotaDecision(allowed=True, limit_usd=UNLIMITED, spent_usd=spent_usd)
    if spent_usd >= limit:
        return QuotaDecision(
            allowed=False,
            reason=(
                f"this month's spend (${spent_usd:.2f}) has reached the "
                f"${limit:.2f} cap on the {user.plan} plan"
            ),
            limit_usd=limit,
            spent_usd=spent_usd,
        )
    return QuotaDecision(allowed=True, limit_usd=limit, spent_usd=spent_usd)
