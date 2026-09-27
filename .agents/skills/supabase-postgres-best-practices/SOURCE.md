# Upstream provenance

- Author/publisher: supabase.
- Repository: https://github.com/supabase/agent-skills
- Revision: `551274ed2fe97c8fea1325f7ceb05803a542f8df`.
- Skill source: https://github.com/supabase/agent-skills/tree/551274ed2fe97c8fea1325f7ceb05803a542f8df/skills/supabase-postgres-best-practices
- License: [MIT](UPSTREAM-LICENSE.txt); preserve upstream credits and notices.

This is a Galaris adaptation, not an unmodified upstream distribution. The imported
material and local adaptations in this directory retain the license identified above;
that statement does not change the license of unrelated repository files.

Local changes narrow discovery, preserve repository authorization boundaries, and route
execution through Docker/Make and the existing domain contracts. Detailed upstream
references are retained and loaded on demand. No upstream executable was run.

Modified or added files: `SKILL.md`, `agents/openai.yaml`.

Omitted upstream packaging/history files: `CHANGELOG.md`.

Review upstream changes against this pinned revision before updating; preserve the
local integration rules rather than replacing the directory blindly.

Additional maintenance: corrected relative reference links where needed and
normalized trailing whitespace in `references/_contributing.md`.

`agents/openai.yaml` includes a default prompt naming the skill, as required by
Galaris architecture checks.
