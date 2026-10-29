<p align="right"><a href="../../fr/user/skills.md">Français</a> · <strong>English</strong></p>

# Use and administer skills

Open **Configure → Skills** (`/skill`). A skill is a package containing `SKILL.md` and
optional references, scripts or templates. It gives an agent a method; connections,
action approvals and resource permissions remain necessary.

## Choose the right collection

| Tab | Contents |
|---|---|
| Skills | Generic catalogue, categories and protected system packages |
| Personal skills | Private packages, each owned by one agent, manually authored or learned by Dream |
| Authorizations | Generic assignments, requiring `SKILL_ASSIGN` |

Personal skills are separate from memories and Documents. Generic packages can be assigned
to multiple agents; personal packages are usable only by their owner. Administration of
that owner does not make their skills usable by your other agents.

In a request, describe the outcome and useful resources: agents are instructed to apply
relevant authorized skills, including their personal methods. In the internal harness, they
load deferred skills when needed and read the relevant sections. Activation makes a skill
available; it does not guarantee the model will choose it. To investigate an omission, check
eligibility and then the execution trace.
A skill is relevant when its method serves the request; appearing in the catalog is not a
reason to load it for an unrelated self-contained answer or simple calculation.

## Learn with Dream

Dream creates a personal package containing its canonical `SKILL.md`. The package detail shows
its evidence, distinct confirming Tasks and reliability. Candidates can be read and edited, but
become usable only after the configured Dream thresholds (three Tasks and a score of 0.75 by
default), within the learned-skill cap. Negative evidence can make them ineligible again.
Manually authored personal packages retain their ordinary activation policy.

Use the same personal package actions to edit, disable, delete or transfer learned procedures.
Reinforcement never reactivates a disabled package, and a late Dream revision cannot overwrite
an intervening edit. Dream uses the personal management delegation of the `skills` Tool.
Disabled and observation modes create no package. Upgrades transfer existing procedures,
evidence and suspensions; name collisions preserve both packages under distinct codes.
The former `?tab=learned` link now opens personal skills.

## Disable a generic package for everyone

In **Skills**, use **Disable for everyone** on a row or in its context menu.
This requires `SKILL_EDIT` and global agent management, and also applies to system packages.
The package disappears from agents' usable skills even when explicitly allowed for an agent
or category. Its files and assignments are preserved. **Enable for everyone** restores the
application of those assignments; the global value in **Authorizations** remains a default.

MCP management remains available with the usual permissions:
`skills_list(administration=true)` and `skill_read(..., administration=true)` can inspect
disabled packages. `skill_set_enabled(skill_id, enabled, expected_revision, administration=true)`
lets an agent with `all` scope disable or re-enable a generic package for everyone.

## Edit a personal package

Under **Personal skills**, search packages or filter by owner agent. Pagination defaults to
50 items, offering 10, 20, 50, 100 or 500. Open a package to inspect files, edit a text file
or label, enable, disable or delete it. Reading follows Skill privileges and management
scope; mutations require `SKILL_EDIT`.

Changes check the revision you read. If another actor modified the package, the conflict
preserves your draft: reload and inspect changes before retrying. Activation applies only
to the owner. Deletion removes the package and its files; system packages stay protected.

**Change owner** transfers a personal package to another active agent you manage. Identity,
author and files remain; activation is removed from the former owner and granted only to
the new owner. Check the recipient and confirm. A code collision or exceeded quota rejects
the transfer without overwriting anything. Personal quotas are 100 packages and 200 MiB
in total per owner.

## Convert between personal and generic

These conversions require Skill editing and global agent management.

- **Make personal** on a non-system generic package asks for an owner agent. Existing
  assignments, global activation and the package's category are removed; it becomes enabled
  only for that owner. Other skills in the category remain unchanged.
- **Convert to generic skill** releases personal ownership, initially enabled for nobody.
  Configure its assignments under **Authorizations** afterwards.

Choose another code if it conflicts. Conversions retain identity, author and files and
preserve a recovery receipt; retrying an uncertain operation must not create a second
conversion. Transferring between agents remains separate from publishing in the generic catalogue.

## Delegate management to an agent

Under **Tools & connections → Connections**, configure **Skills** (`skills`).
New connections are active by default. Without an explicit local scope, agents can manage
their own packages with `personal`. An explicit `usage` scope removes management access.
**Use skills and manage own personal skills** allows agents to create, edit, enable or delete
their own skills while using authorized general skills. It cannot change the files,
activation or assignments of administered general skills. Those operations require team
or global management depending on the action.
Updates preserve existing connections, including deactivations, and their explicit scopes;
reactivate an older disabled connection when needed. Its local
`tools.management_scope` has no global value or inheritance:

| Scope | Capability |
|---|---|
| `usage` | Discover and read usable skills, without management |
| `personal` | Administer its own personal packages; default for an active connection without an explicit scope |
| `team` | Also administer personal packages and generic assignments for agents sharing an active team |
| `all` | Administer all user packages and the generic catalogue; release ownership |

`team` follows the union of active teams, reread on every call. Administration of a foreign
personal package uses an explicit view and never grants usage. Only a human web session with
Connection editing and global agent management can change this delegation. Activating a
connection alone grants no global scope.

Agents use `skills_list` and `skill_read` to discover and read `SKILL.md`. Files use `file_*`
on `galaris://skill/`; personal packages use `galaris://skill/personnal/<agent>/<code>/`
(canonical spelling `personnal`). Creation starts with a valid `SKILL.md` in the authenticated
agent's space. `skill_update`, `skill_set_enabled`, `skill_delete`, `skill_set_authorization`,
`skill_set_category_authorization` and `skill_release_ownership` recheck scope, revision and
permissions on every call.

The former `skill_management` Tool is replaced by `skills`, preserving connections and
settings. Disabled connections stay disabled.

## When changes take effect

Before a new execution, managed harnesses reconcile authorized packages and assignments,
including only the owner's personal packages. Projection failure blocks starting with a
stale copy and remains retryable. An already running Task keeps its loaded context; a
checkpoint resume keeps the context of the operation being reconciled. Future reads and
mutations still recheck current rights.

See also [privileges](../admin/privileges.md), [Tool administration](../admin/tool-administration.md)
and [navigation](navigation.md).
