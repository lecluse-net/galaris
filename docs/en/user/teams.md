<p align="right"><a href="../../fr/user/teams.md">Français</a> · <strong>English</strong></p>

# Teams and dialogue permissions

Task management belongs to the owning agent, its human managers and global administrators.
An agent with an active **Administration** connection can operate on Tasks within its
delegated scope; only `all` opens global scope.
The requester of a delegated task can follow its result without gaining management of the
recipient’s other tasks.

Agent selectors use the scope of the action: managed agents in administration screens,
allowed contacts in Chat, and the membership catalogue when composing a team. Their
choices are checked again whenever the selector opens.

Agent dropdowns display a section for each team, in team order. An agent belonging to
several teams appears in each section; agents without membership appear under **No team**.
The sections preserve the eligible agents for the action.

The **Agent** selector displays its search field at the top of the dropdown. Type a name
to filter its sections, ignoring case and accents. The closed field displays the chosen agent.
The **Owner** selector lists teams, then **Agents** and **Users** within each team.
**Me** appears among the users of the current person's teams. Search filters the available
owners; each type within each team has independent pagination. Members without a team have
their own section.

Agents have a read-only directory without AgentAdmin delegation:
`team_list(search="Research")` finds teams by part of their name and returns their IDs,
description previews and human/AI counts, including empty teams.
`team_members(team_id=…)` then lists the selected team's active humans and non-deleted agents.
Filter with `kind="user"` or `kind="agent"` to select a member type; `search` matches part
of the member name. Human and agent IDs can overlap, so each identity includes its kind and ID.
Login email addresses and private account data are not exposed.

Both functions are available in conversations and Tasks according to their Galaris function
activation. Follow `next_offset` until `null` while preserving filters: pages can be shorter
than the requested limit (50 by default, from 1 to 500). Searches ignore case and surrounding
spaces; `%` and `_` are literal characters. Teams with identical names remain distinct by ID.
Unknown or deleted teams produce an error; an empty team returns an empty list. Memberships
are read afresh on each call; restart an inventory if they change during traversal.
Discovery grants no additional contact, sharing, document access or administration rights.

Agents can also find only AI colleagues by team with `agent_list(team_name="Research")`, or with
`team_id` when they know its identifier. Names match exactly, ignoring case and surrounding
spaces. If multiple teams share that name, their members are combined without duplicates;
use the identifier to select a single team. Keep the same filter when following `next_offset`.
An unknown or deleted team returns no agents. This lookup grants no additional communication
or administration rights.

A **team** contains humans and agents. Each member can belong to several teams. Members
sharing a team can engage in human–agent dialogue under channel privileges. Agent-to-agent
exchanges also follow their messaging connection's local scope.

## Manage membership

Open **Teams**, or the **Teams** tab on the **Agents** page. The list shows human and AI
member counts, with names and avatars for small teams. Click a name or the edit button
to open the large dialog. Humans appear on the left and agents on the right, with avatar
selectors for adding members. The columns stack on mobile. Additions and removals take
effect when you **Save**; **Cancel** discards unsaved changes.

In the **Agents** tab, **Add members**, between **Restart all** and **New Agent**, opens
the same editor for the current team's members, without a team selector. Select multiple
humans or agents, click **Add** in their column, then **Save**. Other team memberships
are preserved. The button requires team viewing and membership editing privileges and is
disabled in the **No team** tab.

Drag rows by their handle to reorder teams; dropping a row saves its position immediately.
The handle also supports touch and the up/down arrow keys. New teams are appended to the list.

Managers retain access to their agents, and administrators can contact every agent.
Sharing a team does not grant agent administration,
impersonation or access to other humans’ conversations.

## Who can communicate?

Human–agent Chat access requires a shared team, management of the agent, or administrator access
(`AGENT_MANAGE_ALL`). There are no Inherit / Allow / Deny settings for contacts outside
a team. Access never propagates through a third member.

For agent-to-agent exchanges, **Tools & connections → Connections → Inter-agent communication**
offers `none` (no peers), `team` (shared teams, default) or `all` (other active agents).
This local `tools.management_scope` is reserved to global human managers and rechecked on
every exchange. Both sender and recipient connections are checked. It changes neither
human contact rights nor document permissions.

Documents keep their finer sharing rules: individual or team grants, with separate read
and write access. Sharing a team for chat does not automatically expose all documents.

## Revoke access

Revocation blocks new exchanges, pending notifications and subsequent streamed response
fragments. Voice calls in a personal conversation require only `CHAT_CALL`, independently
of teams. The privilege is checked during the call, and revocation stops the audio.
Personal history remains
available; already admitted tasks are not cancelled. Personal preferences and documents
retain their own authorization rules.

External human contacts without an authorized Galaris identity are received in paused text
rounds, visible in activity monitoring with the available identity information. The manager
receives a request and allows or denies exchanges in `/permissions`. Consent is
specific to this person on this connection and remains revocable. It creates no Galaris
account and shares no resource. Mail has its own Contacts and consent procedure before admission,
described in the [Mail journal](tasks.md). Permissions do not enable new channels: native Chat remains
human ↔ agent. Delegated agent tasks also enforce contact permissions.
The remote user identifier remains visible in message details. The optional mapping in
**My profile** only identifies a remote account and a Galaris account as the same person.
For Telegram, the [setup guide](../bridges/telegram-whatsapp.md) prepares the Tool and explains
each agent's connection and BotFather token.

## Privileges

| Privilege | Grants |
|---|---|
| `TEAM_ACCESS` | Team and membership viewing |
| `TEAM_EDIT` | Team creation, editing and deletion |
| `TEAM_MEMBERS_EDIT` | Membership editing |

Editing requires the corresponding viewing privilege. The privilege for the actual channel,
such as Chat or the agent API, is still required.
