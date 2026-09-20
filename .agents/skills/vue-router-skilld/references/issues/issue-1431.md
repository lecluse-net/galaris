---
number: 1431
title: Unexpect `scrollBehavior` about `savedPosition` in Safari and Firefox
type: bug
state: open
created: 2022-06-02
url: "https://github.com/vuejs/router/issues/1431"
reactions: 0
comments: 1
labels: "[bug, has workaround, browser quirk]"
---

# Unexpect `scrollBehavior` about `savedPosition` in Safari and Firefox

### Version
4.0.15

### Reproduction link
codesandbox.io







### Steps to reproduce
1. Open the minimal reproduction in firefox.
2. Click the header1.
3. Click the header2.
4. Click the header1 agin.
5. Click the header2 agin.

It also happened in chrome, if you scroll page to the end before click anchor link in step5.

### What is expected?
Jump to the correct header.

### What is actually happening?
Jump to `savedPostion`.

---
It meets code logic, but does not meet the expectations of use.

Notice: I have used CSS scroll-behavior in `:root`.

<!-- genera...