<p align="right"><a href="../../fr/dev/inference-budgets.md">Français</a> · <strong>English</strong></p>

# Inference usage limits by user

In **Monitor → Usage**, **My usage limits** shows the signed-in account's limits. The
table shows the members of any teams you lead, or all other active accounts with the global privilege. It has one row per account and
three fixed limit columns. A limited cell shows a usage bar and amounts marked by `$`.
A blank cell means usage is unlimited. Team leads can open pending requests from the
corresponding row. Personal usage bars also appear above **Configure**. Hover for spending,
the limit and reset time. The bar is green below 50%, blue from 50%, orange from 80%, and
red from 95%. Select it to open the usage page.

| Budget | Start | Reset |
|---|---|---|
| Five hours | First admitted call after inactivity | After five hours, the full amount becomes available and the next call starts a new window. |
| Weekly | Monday at 00:00 UTC by default | Every 168 hours, independently of activity. Previously assigned schedules are kept to preserve associated credits. |
| Monthly | First day of the calendar month at 00:00 UTC | First day of the next calendar month. |

The five-hour and weekly reset rules follow the timing documented by
[Anthropic](https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work).
Galaris measures dollars using its own prices and call traces.

## Configure limits and grant credits

All three budgets are unlimited by default. Every signed-in user can see their usage.

| Permission | Action |
|---|---|
| `LLM_BUDGET_EDIT_OWN` | **Change my limits** in **My usage limits**, including when usage is unlimited. Set all three amounts for your account. |
| `LLM_BUDGET_ADMIN` | The table lists all other active accounts. Click the relevant row or its **Change limits** icon on the right. This privilege also allows editing personal limits. The system Administrator role receives it automatically. |
| Active team lead | Configure limits, issue credit and review requests for other human members of the teams they lead. An account appears once even when the same lead manages several of its teams. |

A blank amount makes the budget unlimited and removes it from the usage display. Zero blocks new
inference. Limits reset automatically and the progress bar
tooltip shows the next reset.

A user with a limit can request a specific amount for one budget. Each budget can have one
pending request. Any of the requester's team leads can approve, reject, or grant credit directly. A grant increases
only the selected limit for the current period and expires at its end. The five-hour window
must be open when a grant is issued. A request can remain pending until the window starts.
Any other exhausted limit keeps blocking calls.

Assign a lead from the [team or user dialog](../user/teams.md).
Only another active team lead can review a request or issue credit. Once reviewed, a request
can produce no further grant. Changes to membership or leadership apply as soon as they are
saved. Editing your own limits still requires `LLM_BUDGET_EDIT_OWN` or `LLM_BUDGET_ADMIN`.

## Accounting and admission

Attribution follows [the source of llm_calls.user_id](llm-attribution.md). Each physical call
counts once at its start time. Archived calls and failed attempts that consumed budget remain
included. Budgets use inference value, with billed cost as a fallback for historical traces.
Known subscription value counts toward the budget. Traces with unknown amounts supply no
cost to add.

An exhausted budget refuses a call before provider submission. Inference APIs return HTTP 429,
or a terminal budget error when an execution already exists. For capped accounts, only one
physical call runs at a time. A per-account PostgreSQL lock serializes the check and call admission
while allowing other accounts to run concurrently. When a provider reports the final price
after a call, that last admitted call can exceed the remaining balance. Further calls are
refused as soon as exhaustion is established. When a shared round has no single requester,
Galaris refuses it if an input belongs to a capped account.

Goal cycles and judgments, attributed automatic tasks, native LLM activities, Dream and
selected deferred operations also check before starting. Queued work can become eligible again
after a reset or grant. The central check covers provider paths that write `llm_calls`.
A new voice session for a capped account uses metered inference and batch transcription
instead of unmetered realtime modes. Personal speech synthesis checks the budget before
calling its provider. Internal embeddings and synthesis outside the call journal are
outside the dollar calculation. Calls without an attributable account are system usage.

## Data and access

| Table | Role |
|---|---|
| `agent_groups`, `team_users` | The team's human lead (`manager_user_id`) and the human memberships that define their scope. |
| `llm_user_budgets` | Per-user decimal limits, weekly reset hour and five-hour window start. The legacy `referrer_user_id` column preserves historical data. |
| `llm_credit_requests` | One pending request per account and period, with decision and reviewing team lead. |
| `llm_credit_grants` | Durable journal of issued credit, issuer, period and associated request. |

All routes under `/api/llm-budget` require an access token bound to an active web session.
Actions use the current session and the server checks the configuration privilege, the active
team memberships managed by the active account, and the self-grant prohibition. Signing out revokes the session. User API tokens,
harness tokens and MCP tools cannot access these routes. The per-account lock and unique
identifiers prevent duplicate grants on retry or concurrent review. Writes relying on team scope
check it under the same coordination lock used by membership and team lead changes.
