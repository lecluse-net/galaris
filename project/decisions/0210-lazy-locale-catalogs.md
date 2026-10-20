# 0210 — Load secondary language catalogs as generated JSON

Date: 2026-10-20

## Context

The initial frontend graph includes every module's English, French and Chinese messages.
Most visitors use one language. Dynamic JavaScript imports reduce eager bytes, but Chromium
can retain a failed module import and prevent a retry without reloading unsaved page state.

## Decision

Keep the existing editable `i18n.ts` catalogs and their validation contracts. A Vite plugin
selects English messages before bundling and generates versioned French and Chinese JSON
assets from the same catalogs. Build-time evaluation permits only catalog data and the two
reviewed shared catalog imports, following the existing catalog checker. Production JSON
uses the same origin, compression and hashed asset handling as other frontend resources.

English remains immediately available for per-key fallback. Bootstrap awaits the browser
language before mounting; failed startup downloads leave a usable English interface.
Language changes load once per language, share concurrent requests and apply messages,
Quasar labels and the HTML language together. Failed HTTP reads can retry without a reload.
Request ordering and a caller-supplied session guard reject obsolete activations. Profile
updates wait for the chosen language and reject obsolete sessions; selection failures are
visible in the existing preference controls.

The service worker precaches both JSON catalogs to preserve installed offline language
switching. Report static bytes separately from startup bytes including the chosen catalog.
PWA installation still downloads all assets; this optimization does not reduce that contract.

## Verification

Catalog tests compare every generated message with the source catalogs, including local
constants and shared Process/Lab messages. Runtime tests cover fallback, concurrency,
failure/retry and session changes. Browser journeys exercise real resource requests,
browser languages and preference persistence. Qualify production startup and PWA updates
with the isolated assembled application.
