---
number: 2622
title: `int` paramParser not modifying value
category: Help and Questions
created: 2026-02-10
url: "https://github.com/vuejs/router/discussions/2622"
upvotes: 1
comments: 1
answered: true
---

# `int` paramParser not modifying value

### Reproduction

https://github.com/OwenVey/vue-router-int-parser

### Steps to reproduce the bug

I have a route file `[id=int].vue` and `route.params.id` has a type of `number` but when I log it or log the `typeof` I am seeing that it is actually a `string`.

My `vite.config.ts` file looks like:
```ts
import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import VueRouter from 'vue-router/vite'

...

---

## Accepted Answer

**@posva** [maintainer]:

You need to use the experimental router:

```ts
import { createWebHistory } from 'vue-router'
import { experimental_createRouter as createRouter } from 'vue-router/experimental'
import { handleHotUpdate, resolver } from 'vue-router/auto-resolver'

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  resolver,
})

if (import.meta.hot) {
  handleHotUpdate(router)
}
```

And also manually register RouterLink and RouterView in `main.ts`:

```ts
import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { RouterLink, RouterView } from 'vue-router'

const app = createApp(App)

app.component('RouterLink', RouterLink)
app.component('RouterView', RouterView)

app.use(router)

app.mount('#app')
```