---
number: 1893
title: Changed behaviour for optional params
type: bug
state: open
created: 2023-06-20
url: "https://github.com/vuejs/router/issues/1893"
reactions: 2
comments: 5
labels: "[bug, has workaround]"
---

# Changed behaviour for optional params

### Reproduction

https://github.com/vuejs/router/blob/main/packages/router/__tests__/router.spec.ts#L300-L328

### Steps to reproduce the bug

- Route with an optional parameter
- Set the parameter
- Unset the parameter with `undefined`

### Expected behavior

I would have expected the parameter to be unset as in versions before 4.2, but I know this might not have been the intended behaviour.

### Actual behavior

This issue is about the changes in https://github.com/vuejs/router/pull/1814

It is a bit of a mess, because several things come together.

1. The documentation says `undefined` and `null` are stringified: https://github.com/vuejs/router/commit/0c912920e39c361210210f5e16ebf8096d2be1fe
2. Before the change they where not stringified, but could actually be used to unset opt...