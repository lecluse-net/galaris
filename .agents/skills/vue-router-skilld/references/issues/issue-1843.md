---
number: 1843
title: 4.2.0 - Type error when extending ComponentCustomProperties
type: other
state: closed
created: 2023-05-12
url: "https://github.com/vuejs/router/issues/1843"
reactions: 9
comments: 12
---

# 4.2.0 - Type error when extending ComponentCustomProperties

### Reproduction

https://stackblitz.com/edit/vitejs-vite-9iezka?file=src/vue.d.ts

### Steps to reproduce the bug

Using vite, create a d.ts file extending ComponentCustomProperties
Use `$route` or `$router` in any component template.
Try to build your code with npm run build

### Expected behavior

When using vue-router 4.1.6, there is no compilation error.

### Actual behavior

Here is the error durring code build : 

```
error TS2339: Property '$route' does not exist on type '{ $: ComponentInternalInstance; $data: {}; $props: { key?: string | number | symbol | undefined; ref?: VNodeRef | undefined; ref_for?: boolean | undefined; ... 8 more ...; style?: unknown; }; ... 10 more ...; $watch<T extends string | ((...args: any) => any)>(source: T, cb: T extends (...args: any) => infer R ? (arg...'.

2   <div>{{ $route.name }}</div>
            ~~~~~~


Found 1 error in src/pages/Home.vue:2·
```

### Additional information

_No response_

---

## Top Comments

**@posva** [maintainer]:

This shouln't be related to vue-router, but it seems like you need to extend vue itself in Vue 3.3  :

```ts
declare module 'vue' {
  interface ComponentCustomProperties {
    $helloWorld: () => void;
  }
}
```

I think others have seen this problem in Nuxt and Vuetify so I will still give it a look and share with team.
I will come back if if I have any news  

**@ByScripts** (+1):

I tried the code from @cturconde 

In `node_modules/vue-router/dist/vue-router.d.ts` at line `1434`, I replaced `declare module 'vue'` with `declare module '@vue/runtime-core'`.

It indeed fixes the issue, but is of course not an acceptable solution.

**@posva** [maintainer]:

I imagine that if you have a package that used the runtime-core you would still see the problem 