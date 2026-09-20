---
number: 2566
title: How to share state across rotes?
category: Help and Questions
created: 2025-10-01
url: "https://github.com/vuejs/router/discussions/2566"
upvotes: 1
comments: 2
answered: true
---

# How to share state across rotes?

What is the ideomatic way to pass parameter from the list view to the detail view for first render.

The goal is to show some data till the full detail object is loadet. I wanna pass the list object to display upfront.

---

## Accepted Answer

**@posva** [maintainer]:

you can pass history state but note it comes with limitations and that it can be accessed directly through `history.state` (in some situations it's disconnected from the current route #2106): `router.push({ state: {} })`.