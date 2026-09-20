<p align="right"><a href="../../fr/user/teams.md">Français</a> · <strong>English</strong></p>

# Teams and dialogue permissions

Task management belongs to the owning agent, its human managers and global administrators.
An agent with an active **Galaris Admin** connection can operate on every agent’s tasks.
The requester of a delegated task can follow its result without gaining management of the
recipient’s other tasks.

Agent selectors use the scope of the action: managed agents in administration screens,
allowed contacts in Chat, and the membership catalogue when composing a team. Their
choices are checked again whenever the selector opens.

A **team** contains humans and agents. Each member can belong to several teams. Members
sharing a team can talk through the available channels without an additional rule.

## Manage membership

Open **Teams**, or the **Teams** tab on the **Agents** page. The list shows human and AI
member counts, with names and avatars for small teams. Click a name or the edit button
to open the large dialog. Humans appear on the left and agents on the right, with avatar
selectors for adding members. The columns stack on mobile. Additions and removals take
effect when you **Save**; **Cancel** discards unsaved changes.

Drag rows by their handle to reorder teams; dropping a row saves its position immediately.
The handle also supports touch and the up/down arrow keys. New teams are appended to the list.

Managers retain access to their agents, and administrators can contact every agent.
Sharing a team does not grant agent administration,
impersonation or access to other humans’ conversations.

## Who can communicate?

Chat access requires a shared team, management of the agent, or administrator access
(`AGENT_MANAGE_ALL`). There are no Inherit / Allow / Deny settings for contacts outside
a team. Access never propagates through a third member. Two agents must share a team
to communicate with one another.

Documents keep their finer sharing rules: individual or team grants, with separate read
and write access. Sharing a team for chat does not automatically expose all documents.

## Revoke access

Revocation blocks new exchanges, pending notifications and subsequent streamed response
fragments. Voice calls in a personal conversation require only `CHAT_CALL`, independently
of teams. The privilege is checked during the call, and revocation stops the audio.
Personal history remains
available; already admitted tasks are not cancelled. Personal preferences and documents
retain their own authorization rules.

External contacts must be linked to a verified Galaris identity to engage an agent, including
through asynchronous messages. Permissions do not enable new channels: native Chat remains
human ↔ agent. Delegated agent tasks also enforce contact permissions.

## Privileges

| Privilege | Grants |
|---|---|
| `TEAM_ACCESS` | Team and membership viewing |
| `TEAM_EDIT` | Team creation, editing and deletion |
| `TEAM_MEMBERS_EDIT` | Membership editing |

Editing requires the corresponding viewing privilege. The privilege for the actual channel,
such as Chat or the agent API, is still required.
