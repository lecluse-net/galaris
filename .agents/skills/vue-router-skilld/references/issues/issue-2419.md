---
number: 2419
title: Active class not applied on `RouterLink` when using `to` with `string` or object with `path` key
type: bug
state: open
created: 2024-12-08
url: "https://github.com/vuejs/router/issues/2419"
reactions: 2
comments: 2
labels: "[bug, has workaround]"
---

# Active class not applied on `RouterLink` when using `to` with `string` or object with `path` key

### Reproduction

https://stackblitz.com/edit/vitejs-vite-a1m7gbnq

### Steps to reproduce the bug

1. Open the reproduction link
2. Click on third item (`Go to Feature one`)
3. Check the active classes applied to the first and second links.

### Expected behavior

The `RouterLink` component with the `/features` value is expected to have the active class (`router-link-active`) applied when the current route is `/features/one`, regardless of how the `to` prop value is provided.







### Actual behavior

The active class (`router-link-active`) is applied only when the `to` prop is passed with a route `name`. However, for another `RouterLink` where the `to` prop is provided as a string, the active class is not applied.

...