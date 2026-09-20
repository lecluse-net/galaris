---
number: 1324
title: Suspended component in nested route result in child route mounted twice
type: bug
state: closed
created: 2022-02-25
url: "https://github.com/vuejs/router/issues/1324"
reactions: 5
comments: 1
labels: "[bug, external, feat:suspense]"
---

# Suspended component in nested route result in child route mounted twice

### Version
4.0.0

### Reproduction link
codesandbox.io




- from https://github.com/vuejs/router/issues/626#issuecomment-1048609550


### Steps to reproduce
https://codesandbox.io/s/lively-mountain-o395nx?file=/src/UserCenter/Push.vue

### What is expected?
push once

### What is actually happening?
push twice



---

## Top Comments

**@posva** [maintainer] (+1):

I tested with up-to-date dependencies and there is no longer a double push. This was patched in https://github.com/vuejs/core/pull/10055