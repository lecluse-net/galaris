---
number: 626
title: keep-alive component in nested route result in child route mounted twice
type: question
state: open
created: 2020-12-01
url: "https://github.com/vuejs/router/issues/626"
reactions: 52
comments: 44
labels: "[help wanted, external, feat:keep-alive]"
---

# keep-alive component in nested route result in child route mounted twice

### Version
3.0.3

### Reproduction link
https://codesandbox.io/s/nifty-roentgen-67uyr
without vue router







### Steps to reproduce
There is 5 files in the project. These files are App.vue, UserCenter/Index.vue, UserCenter/Push.vue, List/Index.vue, L...

---

## Top Comments

**@posva** [maintainer] (+13):

The problem is the same as https://github.com/vuejs/vue/issues/8819 which I don't know if it's expected or not. @yyx990803 is it normal for an inactive kept-alive component to keep _rendering_ while inactive?

In the context of vue-router I tried internally avoiding rendering the router-view when the component is inactive, but it's too late, it still gets to mount the children once, resulting in mounting two Detail pages. So I tried not changing the route for nested router views but it turns out the `onDeactivated` hook triggers **after** computed based on the current route location, not allow...

**@edison1105** [maintainer]:

It seems like a `Vue-router` bug.

**@danitatt** (+3):

Also ran into the mounted issue in nested routes when using keep-alive, which causes repeated calls to the database :(
Didn't find a solution :(

vue@3.0.5
vue-router@4.0.3