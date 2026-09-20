---
number: 2501
title: "Can we \"compile\" a path without using path-to-regexp"
category: Help and Questions
created: 2025-05-15
url: "https://github.com/vuejs/router/discussions/2501"
upvotes: 1
comments: 1
answered: true
---

# Can we "compile" a path without using path-to-regexp

I wonder what is the best way to, for example, to compile a path and params (`/users/:id`, `{ id: 5 }` => `/users/5`) the same way as vue-router does ?

```ts
compilePath('/users/:id', { id: 5 }) // /users/5
```

I want to do it for external paths (that are not defined as a route in vue-router).

We are currently using `path-to-regexp` v6 `compile` function for that, which works rather well. But while upgrading dependencies I see the syntax changed for the v8 and that vue-router internalized the logic.

Can we use some functions exposed by `vue-router` ?


---

## Accepted Answer

**@posva** [maintainer]:

They won’t be exposed but you can copy the code needed into your project, it’s under the same MIT license 