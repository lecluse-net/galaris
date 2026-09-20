---
number: 2435
title: Navigation breaks upon unrelated error
category: Help and Questions
created: 2025-01-10
url: "https://github.com/vuejs/router/discussions/2435"
upvotes: 1
comments: 1
answered: true
---

# Navigation breaks upon unrelated error

Hello there,

We are migrating an app from webpack to vite, and while doing so I found a strange behavior. It seems that with our new version, an error (like component script execution) will freeze the navigation. You can find a reproduction here 
https://stackblitz.com/edit/vitejs-vite-cxexlrbk?file=src%2FApp.vue,src%2Fmain.ts,src%2Frouter.ts,package.json,src%2FHome.vue,src%2FSync.vue&terminal=dev

Home page is fine, Sync page has a div with a class that tries to access an item on undefined. Once arriving on the sync page and the error triggers, the Home page (with "Home view" message) is can not be accessed anymore (though the url will change).

Is this intended ? For our project it can be inconvenient as multiple teams work on the same codebase and sometimes an error (that doesn'...

---

## Accepted Answer

**@posva** [maintainer]:

This wasn't intended but was part of the new behavior of RouterView with Vue 3. In practice, you are not expected to deploy applications with these kind of errors as they mean the page will **always** break when loaded. You can catch them with an error handler:

```ts
const app = createApp(App)
app.config.errorHandler = (e) => {
  console.log('OH NO', e)
}
```