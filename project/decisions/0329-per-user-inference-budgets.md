# 0329 — Per-user inference budgets

Status: accepted.

Per-user budgets belong to the LLM domain. Each physical call retains its budget user and
contributes once to the three windows by start time. The five-hour window starts at call
admission, the weekly window has a fixed UTC renewal hour, and the monthly window follows the
UTC calendar. A null limit keeps a window unlimited.

The physical gateway is authoritative for admission. A transaction lock keyed by the budget
user serializes the admission of capped accounts before provider prices settle. A known
automatic trigger checks eligibility before advancing, while the physical check covers the
race between eligibility and supplier submission.

Credit requests and window-scoped grants are separate records. Each grant belongs to the
active window at issuance and expires with it. Policy changes and credit
decisions require an access token bound to an active web session. Grant authority
comes from the current active lead of a recipient's team and excludes the recipient account.
The lead can also set limits for the other human members of that team. Several team leads can
review the same member's request, and the first committed decision is final. Configuration is separate
from user account administration. `LLM_BUDGET_EDIT_OWN` scopes policy changes to the caller's
own amounts. `LLM_BUDGET_ADMIN` also permits configuring other accounts. A team has one
human lead, stored on the team and assigned through its editor or a member's account editor by an
authorized human. Existing teams receive an explicit assignment when configured. Previous per-user
referrer data is preserved for history. Signed-in users can always view their own limited budgets.

[Budget behavior and data contract](../../docs/en/dev/inference-budgets.md)
