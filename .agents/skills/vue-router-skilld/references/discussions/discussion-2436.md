---
number: 2436
title: How to Reset Filters with Query Params Without Triggering Navigation Guard Loops?
category: Help and Questions
created: 2025-01-13
url: "https://github.com/vuejs/router/discussions/2436"
upvotes: 1
comments: 1
answered: true
---

# How to Reset Filters with Query Params Without Triggering Navigation Guard Loops?

Hello,

I have a design issue with my Vue Router setup. I’m working on dashboard pages that contain dynamic filters, which are stored in a Pinia store. The query params in the URLs of my dashboards are updated to reflect the active filters. This allows filters to persist when the page is reloaded or if the URL with query params is shared with another user.  I’m using a watcher in my Pinia store to handle this:

```javascript
const queryParams = computed(() => {
  return {
    themes: selectedThemesKeys.value.join(),
    sources: selectedSourcesKeys.value.join(),
    presetPeriod: selectedPresetPeriod.value,
    customStart: customPeriod.value.start,
    customEnd: customPeriod.value.end,
  }
})

watch(queryParams, () => {
  router.replace({ query: queryParams.value })
})
```...

---

## Accepted Answer

**@posva** [maintainer]:

Since you are in a navigation guard, you can trigger a redirect:

```ts
router.beforeEach(async (to, from) => {
  if (from.name && to.name !== from.name && to.name === 'dashboard' && !to.redirectedFrom) {
    return { ...to, query: {} }
  }
})
```