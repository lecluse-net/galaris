# Upstream provenance

- Author/publisher: openai.
- Repository: https://github.com/openai/skills
- Revision: `49f948faa9258a0c61caceaf225e179651397431`.
- Skill source: https://github.com/openai/skills/tree/49f948faa9258a0c61caceaf225e179651397431/skills/.curated/security-threat-model
- License: [Apache-2.0](LICENSE.txt); preserve upstream credits and notices.

This is a Galaris adaptation, not an unmodified upstream distribution. The imported
material and local adaptations in this directory retain the license identified above;
that statement does not change the license of unrelated repository files.

Local changes narrow discovery, preserve repository authorization boundaries, and route
execution through Docker/Make and the existing domain contracts. Detailed upstream
references are retained and loaded on demand. No upstream executable was run.

Modified or added files: `SKILL.md`, `agents/openai.yaml`, `references/prompt-template.md`.

Review upstream changes against this pinned revision before updating; preserve the
local integration rules rather than replacing the directory blindly.

Additional maintenance: corrected relative reference links where needed and
normalized trailing whitespace in `references/prompt-template.md`.
