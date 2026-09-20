---
number: 1429
title: Extending RouterLink example does not compile in TypeScript
type: docs
state: open
created: 2022-06-01
url: "https://github.com/vuejs/router/issues/1429"
reactions: 4
comments: 4
labels: "[enhancement, typescript, docs]"
---

# Extending RouterLink example does not compile in TypeScript

### Version
4.0.15

### Reproduction link
stackblitz.com







### Steps to reproduce
There's an issue with reactivity in the template when extending the routerlink as per example from the docs: https://router.vuejs.org/guide/advanced/extending-router-link.html

The culprit is the `...RouterLink.props` prop spread, which (for some reason) makes props unavailable to the template unless you destructure the props with `toRefs`.

I'm not sure if this a bug in vue-router, a bug in vue, or a limitation/side-effect in general, but the example won't properly build and will throw TS errors (it also throws errors in dev, as you can see in the reproduction).

Uncomment the commented o...