---
name: playwright-best-practices
description: Write and debug Playwright component and end-to-end tests, including flaky waits, network failures, authentication, accessibility, and real-time interactions. Use for browser test work, not ordinary Vue implementation or simply opening a page.
---
# Playwright Best Practices

Write and diagnose browser tests around observable user actions and durable outcomes.
Read only the references relevant to the changed journey.

## Galaris integration

- Inspect the existing scenarios in `front/browser-tests/`, component harnesses in
  `front/test-support/`, and the repository's functional test catalog before adding coverage.
- Use `make tests-front-components ARGS='...'` for component interactions and
  `make tests-e2e ARGS='...'` for assembled journeys. Inspect each target's accepted arguments.
  `make tests-browser` exercises the browser executor, not the frontend journey suite.
- All Node/npm/Playwright commands in the references are examples to run through the project's
  Docker/Make tooling. Do not run them on the host, install a second test stack, or start a
  competing dev server. Use `front-ui-conventions` and the applicable Vue skills when editing
  components; use the installed browser skill for interactive in-app browser control.
- Preserve the viewport contract: mobile below 1024 CSS px, desktop from 1024 px. Use synthetic
  fixtures and isolated users; replace external boundaries rather than internal workflow code.
- Assert usable actions, content, permissions, and persistent effects. Use visual comparisons
  only for a relevant visual contract; do not freeze incidental colors, widths, or button order.
- Apply `AGENTS.md`'s frontend coverage decisions before creating a scenario. Local visual
  adjustments and early layout iterations need rendered inspection, not permanent assertions.
  Centralize documented shared guidelines in reusable coverage; extend existing scenarios
  for distinct consumer behavior rather than duplicating a test for every page or modal.
- Diagnose a failure before changing locators or assertions: it can expose a product defect.
  Preserve traces and relevant console/network errors. Repeat runs when investigating flakiness
  or concurrency, not automatically after every passing change.

## Select references by task

| Task | Read |
|---|---|
| Locators and reliable waiting | [Locators](core/locators.md), [assertions and waits](core/assertions-waiting.md) |
| Test isolation and fixtures | [Fixtures](core/fixtures-hooks.md), [test data](core/test-data.md) |
| Vue component interactions | [Component testing](testing-patterns/component-testing.md), [Vue](frameworks/vue.md) |
| Failure diagnosis | [Debugging](debugging/debugging.md), [flaky tests](debugging/flaky-tests.md), [console errors](debugging/console-errors.md) |
| Error, retry, and late responses | [Error testing](debugging/error-testing.md), [network controls](advanced/network-advanced.md) |
| Chat reconnect and PWA behavior | [WebSockets](browser-apis/websockets.md), [service workers](browser-apis/service-workers.md) |
| Authentication, RBAC, concurrent users | [Authentication](advanced/authentication.md), [auth flows](advanced/authentication-flows.md), [multi-user tests](advanced/multi-user.md) |
| Accessibility and responsive journeys | [Accessibility](testing-patterns/accessibility.md), [mobile testing](advanced/mobile-testing.md) |
| Localization | [i18n](testing-patterns/i18n.md) |
| Time-dependent behavior | [Clock control](advanced/clock-mocking.md) |
| Files and embedded documents | [Uploads/downloads](testing-patterns/file-upload-download.md), [iframes](browser-apis/iframes.md) |
| Performance measurements | [Performance testing](testing-patterns/performance-testing.md) |
| Choosing test layers and boundaries | [Test architecture](architecture/test-architecture.md), [when to mock](architecture/when-to-mock.md) |
| Container or CI test setup | [Docker](infrastructure-ci-cd/docker.md), [GitLab](infrastructure-ci-cd/gitlab.md), [GitHub Actions](infrastructure-ci-cd/github-actions.md) |

Additional upstream references are retained in `core/`, `advanced/`, `architecture/`,
`browser-apis/`, `debugging/`, `frameworks/`, `infrastructure-ci-cd/`, and `testing-patterns/`.
Search those directories for a specific uncovered task rather than loading the whole collection.

## Provenance

See [SOURCE.md](SOURCE.md) for the pinned upstream revision, license, and local changes.
