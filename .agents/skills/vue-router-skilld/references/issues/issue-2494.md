---
number: 2494
title: Typed routes out of the box (without file based routing)
type: other
state: open
created: 2025-04-21
url: "https://github.com/vuejs/router/issues/2494"
reactions: 5
comments: 1
---

# Typed routes out of the box (without file based routing)

### What problem is this solving

Navigate to an unknown route isn't catch by typescript.

```ts
export const router = createRouter({
  routes: [
    { path: "/foo", component: () => import("./pages/foo.vue") },
  ],
  history: createWebHistory(),
});

router.push("/bar"); // <------ No type error
```

### Proposed solution

Infer types so `router` is strongly typed with declared routes.

### Describe alternatives you've considered

unplugin-vue-router but its file based routing.

---

## Top Comments

**@dmitry-lavrik**:

Hello!

I just recently made a library that might help you - https://github.com/dmitry-lavrik/vue-routes-to-types 

It outputs types for RouteNamedMap from routes array.

Hopefully, someday such functionality will be created in the Vue-router core. Or they will put a link from the documentation to this library :)