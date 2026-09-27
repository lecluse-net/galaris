# Upstream provenance

- Author/publisher: currents-dev.
- Repository: https://github.com/currents-dev/playwright-best-practices-skill
- Revision: `283d5cbc5d11aac1abda058b16ad22c317d54dc0`.
- Skill source: https://github.com/currents-dev/playwright-best-practices-skill/tree/283d5cbc5d11aac1abda058b16ad22c317d54dc0/playwright-best-practices
- License: [MIT](UPSTREAM-LICENSE.txt); preserve upstream credits and notices.

This is a Galaris adaptation, not an unmodified upstream distribution. The imported
material and local adaptations in this directory retain the license identified above;
that statement does not change the license of unrelated repository files.

Local changes narrow discovery, preserve repository authorization boundaries, and route
execution through Docker/Make and the existing domain contracts. Detailed upstream
references are retained and loaded on demand. No upstream executable was run.

Modified or added files: `SKILL.md`, `agents/openai.yaml`.

Review upstream changes against this pinned revision before updating; preserve the
local integration rules rather than replacing the directory blindly.

Additional maintenance: corrected relative reference links where needed and
normalized trailing whitespace in `advanced/network-advanced.md`, `browser-apis/service-workers.md`, `debugging/error-testing.md`, `debugging/flaky-tests.md`, `infrastructure-ci-cd/performance.md`, `testing-patterns/graphql-testing.md`, `testing-patterns/visual-regression.md`.

`agents/openai.yaml` includes a default prompt naming the skill, as required by
Galaris architecture checks.
