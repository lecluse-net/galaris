---
number: 1617
title: Warning of invalid param for catch all route with named route redirect
type: feature
state: open
created: 2022-11-19
url: "https://github.com/vuejs/router/issues/1617"
reactions: 9
comments: 8
labels: "[enhancement, good first issue, has workaround]"
---

# Warning of invalid param for catch all route with named route redirect

### Version
4.1.6

### Reproduction link
jsfiddle.net/z0kytrqj/16/







### Steps to reproduce
Navigate to a catch all route with a named route redirect
```ts
  {
    path: '/:pathMatch(.*)*',
    redirect: { name: 'HOME' }
  }
```

### What is expected?
No warnings

### What is actually happening?
Warning displayed: Discarded invalid param(s) "pathMatch" when navigating. See https://github.com/vuejs/router/blob/main/packages/router/CHANGELOG.md#414-2022-08-22 for more details.



---

## Top Comments

**@posva** [maintainer] (+16):

This is due to the implicit parameter being passed during a redirection. You can workaround it by passing an empty object of Params alongside the name of the route: `redirect: { name: 'home', params: {} }` or a function to pick the params you want: `redirect: to => ({ name: '...', params: { id: to.id }})`

I’m unsure if this warning can be avoided without removing it. Worst case scenario we can also mention the workaround in the warning

**@posva** [maintainer] (+1):

Sure

**@posva** [maintainer]:

It's the very first comment, I added some extra examples: https://github.com/vuejs/router/issues/1617#issuecomment-1320941431