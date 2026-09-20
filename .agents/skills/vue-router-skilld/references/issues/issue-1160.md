---
number: 1160
title: Add support for params generic in useRoute
type: feature
state: open
created: 2021-10-16
url: "https://github.com/vuejs/router/issues/1160"
reactions: 13
comments: 6
labels: "[enhancement, typescript, has workaround]"
---

# Add support for params generic in useRoute

### What problem does this feature solve?
**Typing of params from useRoute.**

When you have function with typed arguments

```
const someFn = (id: string, type: ResourceType) => {}
```

And when you try to pass a `route.params` as an argument

```
const route = useRoute()
someFn(route.params.resourceId, route.params.type)
```
You will get error

Argument of type 'string | string[]' is not assignable to parameter of type 'string'.
  Type 'string[]' is not assignable to type 'string'.
  
Screenshot of problem




### What does the proposed API look like?
```
type Params = {
    id: string
    type: ResourceType
}
const route = useRoute<Params>() // route.params will be typed
```

### Pull Request
https://github.com/vuejs/vue-router-next/pull/1159



---

## Top Comments

**@posva** [maintainer] (+5):

This is interesting. I think we can push it a bit  further the type génération for routes and the PR that @pikax sent #872 , maybe there is a way to extend the defined routes and then provide (with autocompletion) a name generic:

```js
// given a route { path: '/users/:id', name: 'users' ... }
useRoute<'users'>() // route type with params: { id: string }
// given a route { path: '/posts/:slugs*', name: 'posts' ... }
useRoute<'posts'>() // route type with params: { slugs?: string[] }
```

**@posva** [maintainer] (+2):

as mentioned in https://github.com/vuejs/router/pull/1159#issuecomment-1055275856 let's keep this in userland for the moment

```ts
import { RouteParams } from 'vue-router'
import { computed } from 'vue'

function useParams<P extends RouteParams>() {
  const route = useRoute()
  return computed(
    () => route.params as P
  )
}
```

**@fyapy** (+3):

@posva If we have plans for a useRoute hook, may be we can add a useParams hook with generic support? Because at the moment the problem with typing params is very annoying 
### What does the proposed API look like?
```typescript
type Params = {
    id: string
    type: ResourceType
}
const params = useParams<Params>() // params with types information
```