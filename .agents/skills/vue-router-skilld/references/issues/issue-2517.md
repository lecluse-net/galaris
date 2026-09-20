---
number: 2517
title: Parameters followed by an escaped colon are mis-parsed
type: bug
state: open
created: 2025-06-24
url: "https://github.com/vuejs/router/issues/2517"
reactions: 0
comments: 1
labels: "[bug, contribution welcome, has workaround]"
---

# Parameters followed by an escaped colon are mis-parsed

### Reproduction

https://paths.esm.dev/?p=AAMeJQ2BuMDAFAF2JXAJkhXgAXQAzhugPUAFGBrQSoB0AJln0DVAEgARIKDWCMwAtwdU5FqlITEMcMRpSTgHfQgIKUrpRABA&t=/a/section:abc

### Steps to reproduce the bug

There are two related bugs, but seem to be triggered by the same issue (the reproduction link shows both bugs).

1. Create a route that contains `\:` immediately following a parameter, e.g. `{ path: '/:foo([^:]+)\\:abc' }`
2. Attempt to load the route by navigating to (say) `section:abc`; the attempt will fail (but should succeed)
3. Attempt to load the route by navigating to (say) `sectionabc`; the attempt will succeed (but should fail)
4. Also note that `$route.params` is incorrect in the above case, containing `{ 'foo:': ... }` instead of `{ foo: ... }` (note the colon)

### Expected behavior

...