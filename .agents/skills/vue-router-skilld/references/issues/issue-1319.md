---
number: 1319
title: Nested routes + `<Suspense>` triggers Vue unhandled error
type: bug
state: closed
created: 2022-02-23
url: "https://github.com/vuejs/router/issues/1319"
reactions: 6
comments: 7
labels: "[bug, external, feat:suspense]"
---

# Nested routes + `<Suspense>` triggers Vue unhandled error

### Version
4.0.12

### Reproduction link
stackblitz.com


### Steps to reproduce
When there are nested routes in which each nested RouterView has its own Suspense, navigating again before suspense resolves triggers  a Vue internals bug.

Click the navigate button multiple times in succession. You should see the following errors:

```bash
[Vue warn]: Unhandled error during execution of scheduler flush. This is likely a Vue internals bug. Please open an issue at https://new-issue.vuejs.org/?repo=vuejs/core 
  at <RouterView> 
  at <App>

Uncaught (in promise) TypeError: Cannot read properties of null (reading 'parentNode')
  at parentNode (runtime-dom.esm-bundler.js:35:30)
  at ReactiveEffect.componentUpdateFn [as fn] (runtime-core.esm-bundler.js:5109:17)
  at ReactiveEffect.run (reactivity.esm-bundler.js:167:25)
  at callWithErrorHandling (runtime-core.esm-bundler.js:155:36)
  at flushJobs (runtime-core.esm-bundler.js:394:17)
```

### What is expected?
I'm expecting that there would not be an error.

### What is actually happening?
There is an error.

---
I'm raising this here but please let me know if you think this isn't an issue with the router and is in fact a vue core bug.



---

## Top Comments

**@posva** [maintainer] (+4):

Managed to reproduce with a smaller version without Vue Router:

This reminds me of an error with Suspense in core but I couldn't find the issue. I will have to take a look see if it's specific to router. This will be necessary for `onBeforeNavigate()`

**@posva** [maintainer] (+3):

Tested out with latest vue and vue router and the problem is no longer there  