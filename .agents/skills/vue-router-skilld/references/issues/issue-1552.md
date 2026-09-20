---
number: 1552
title: RouterLink isActive slot not true when it should be
type: docs
state: open
created: 2022-09-14
url: "https://github.com/vuejs/router/issues/1552"
reactions: 2
comments: 2
labels: "[contribution welcome, docs]"
---

# RouterLink isActive slot not true when it should be

### Version
4.1.5

### Reproduction link
jsfiddle.net/16nudxt0/







### Steps to reproduce
In the jsfiddle, click on "bar".

### What is expected?
I would expect the bool values after "foo" to show "true, false", because `/foo/bar` should indicate that `/foo` is active (but not exact).

### What is actually happening?
The "foo" link says isActive is false.

