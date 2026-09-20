---
number: 2447
title: HTML 5 Web History
category: Help and Questions
created: 2025-01-27
url: "https://github.com/vuejs/router/discussions/2447"
upvotes: 1
comments: 2
answered: true
---

# HTML 5 Web History

I moved up from Vue 2 to Vue 3 recently, and trying to get the HTML 5 Web History working the same way as in Vue 2.

So I set the history mode using "createWebHistory", and everything seems fine, except when I click on the same link (ie. on dashboard, then I click on a side menu that go to dashboard again), on Vue 3 (vite), the whole page reload, but in Vue 2 (cli-serve), if I click on the same link, the page will not reload.

And if I use createWebHashHistory on Vue 3, the page also won't reload.

So am I missing some configuration some where?

---

## Accepted Answer

**@posva** [maintainer]:

That behavior hasn't changed from Vue Router 3 to 4. RouterLink will not reload in both cases. A boiled down repro could help reproduce