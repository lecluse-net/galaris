---
number: 2582
title: It affects the operation of vite when in dev mode.
category: Help and Questions
created: 2025-10-31
url: "https://github.com/vuejs/router/discussions/2582"
upvotes: 1
comments: 1
answered: true
---

# It affects the operation of vite when in dev mode.

Sample: https://github.com/IAALAI/ext_test_1

Is it similar to affecting Vite's workflow?

In this project, `@samrum/vite-plugin-web-extension` was added. 
It would normally open a websocket connection to localhost:5173.
 After adding vue-router, it attempts to redirect to `localhost:5173//` instead of the expected `//`.
 It appears to be covering the functionality of @samrum/vite-plugin-web-extension.

---

## Accepted Answer

**@posva** [maintainer]:

You probably need to use the `createMemoryHistory()` but you should ask in the other repo instead