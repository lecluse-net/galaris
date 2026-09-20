---
number: 2484
title: Using event handler with `RouterLink` combined with `vueCompilerOptions` `strictTemplates` gives TS error
type: other
state: closed
created: 2025-03-28
url: "https://github.com/vuejs/router/issues/2484"
reactions: 2
comments: 4
labels: "[contribution welcome, typescript]"
---

# Using event handler with `RouterLink` combined with `vueCompilerOptions` `strictTemplates` gives TS error

### Reproduction

https://github.com/line301u/reproduction-vuerouter-issue-routerlink-stricttemplates

### Steps to reproduce the bug

**The steps are already added to the reproduction:**
run `pnpm run type-check` to get the TS error

**If setting up a new vue project, use these steps to reproduce:**
In your the tsconfig.json, add:
```
  "vueCompilerOptions": {
    "strictTemplates": true
  },
```

Use RouterLink component with any event handler - e.g.: 
`<RouterLink to="/" @focus="console.log('focus')" />`

Run typecheck with the following command: `pnpm run type-check`

### Expected behavior

I wouldn't expect to get an error for using event handlers on the RouterLink component

### Actual behavior

...