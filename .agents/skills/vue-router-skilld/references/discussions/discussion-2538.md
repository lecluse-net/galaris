---
number: 2538
title: Does anyone use this crap with typescript? How do you use NavigationGuardNext if it accepts nothing that is listed as param?
category: Help and Questions
created: 2025-08-04
url: "https://github.com/vuejs/router/discussions/2538"
upvotes: 1
comments: 1
answered: true
---

# Does anyone use this crap with typescript? How do you use NavigationGuardNext if it accepts nothing that is listed as param?

```
function handleRoute(...): RouteLocationRaw | undefined {...}

onBeforeRouteUpdate((to, from, next) => {
next(handleRoute(to)); // Type error here: Argument of type 'string | RouteLocationAsRelativeGeneric | RouteLocationAsPathGeneric | undefined' is not assignable to parameter of type 'NavigationGuardNextCallback'.
});
```

Why is this happening? I know this is more like a typescript issue, but i think this is very common scenario. How to solve this?

---

## Accepted Answer

**@posva** [maintainer]:

You have to revisit the way to communicate in discussions my friend. It's not okay to start by a sentence like "does anyone use this crap". I'm locking the conversation because of this.

The type error should give you more insights about which type is not working.

BTW, use a `return` instead of `next`, that's the old v3 version, it will be deprecated soon:

```ts
onBeforeRouteUpdate((to, from) => {
   return handleRoute(to)
})
```