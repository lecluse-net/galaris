---
number: 2455
title: Using URLSearchParams for query
category: Help and Questions
created: 2025-02-01
url: "https://github.com/vuejs/router/discussions/2455"
upvotes: 1
comments: 2
answered: true
---

# Using URLSearchParams for query

Is there a reason why `query` doesn’t support passing `URLSearchParams` instance directly? We can transform it to plain object with `Object.fromEntries`, but it would be really nice if it can accept search params instance to align with the web platform.

---

## Accepted Answer

**@posva** [maintainer]:

Historically, it wasn't supported for compatibility reasons but nowadays, the main issue with URLSearchParams is its poor performance.