---
number: 2589
title: "Version 4.6.0: Scroll to the top when reloading instead of maintaining the scroll position"
category: Help and Questions
created: 2025-11-30
url: "https://github.com/vuejs/router/discussions/2589"
upvotes: 1
comments: 1
answered: true
---

# Version 4.6.0: Scroll to the top when reloading instead of maintaining the scroll position

Since upgrading from 4.5.1 to 4.6.0, I have noticed unusual scrolling behavior when I scroll down a page and refresh it via the browser. Unfortunately, I am uncertain whether this is a bug or if there is a new setting in version 4.6.0 that I am missing.

What happens with version 4.6.0:
1. I scroll down
2. Reload the page
3. Page displays the top content

What I expect (as in 4.5.1):
1. I scroll down
2. Reload the page
3. Scroll position remains the same as before reloading.

I have created a small demo package to reproduce the problem. Download, install dependencies, go into dev mode, open frontend, navigate to the about page, scroll down, reload the page.

I also activated scroll-behavior: smooth; in app.vue, which visualizes the problem even better.

I use MacOS (26.1 (2...

---

## Accepted Answer

**@posva** [maintainer]:

Ah I think I see what you mean, it's when you reload after immediately navigating somewhere and scrolling around. This is because of e0e38abd. Removing `beforeunload` was necessary so now there is this specific case where the save of the scroll position doesn't work. I added this to https://github.com/vuejs/router/issues/2403 to not forget