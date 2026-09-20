---
number: 2587
title: "How to catch the \"Uncaught (in promise) Error...\" when beforeEach return false"
category: Help and Questions
created: 2025-11-21
url: "https://github.com/vuejs/router/discussions/2587"
upvotes: 1
comments: 1
answered: true
---

# How to catch the "Uncaught (in promise) Error..." when beforeEach return false

Some pages/routes requires redirect to sso/oauth to login, then we redirect away with `location.href` and `return false` in `router.beforeEach` guard to block render, however, there is always an `Uncaught (in promise) Error: Navigation aborted from "/" to ...`, how to catch this `Uncaught`? or what is the best practise for this scene?

---

## Accepted Answer

thanks for your reply.

I tried a new project, debug and compare two projects, move / remove code, and finally found the error is thrown by `router.isReady` in my `App.vue`, append catch to it solved the uncaught!