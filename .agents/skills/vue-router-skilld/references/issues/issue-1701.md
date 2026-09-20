---
number: 1701
title: View Component unnecessarily updates when child route changes
type: bug
state: open
created: 2023-02-16
url: "https://github.com/vuejs/router/issues/1701"
reactions: 2
comments: 9
labels: "[bug]"
---

# View Component unnecessarily updates when child route changes

### Version
4.1.6

### Reproduction link
codesandbox.io

### Steps to reproduce
1. Open linked CodeSandbox
2. Observe Console
3. Click on "Home - A", and then on "Home - B"

### What is expected?
Should not log at all, because the component has receives no props and does not depend on any reactive data from the router.

So when a child route changes, it should not update.

### What is actually happening?
Home.vue console.logs 3 times, meaning it re-rendered multiple times.


---
I'm pretty sure the reason for that is that `router-view` needs to re-render multiple times, and each time, a new `onVNodeUnmounted` callback is added to the VieComponent vnode's props object here:

https://github.com/...