---
number: 1301
title: There should be a simpler alternative to the`(.*)?` pattern
type: other
state: open
created: 2022-02-08
url: "https://github.com/vuejs/router/issues/1301"
reactions: 2
comments: 9
labels: "[discussion]"
---

# There should be a simpler alternative to the`(.*)?` pattern

### Version
4.0.12

### Reproduction link
jsfiddle.net







### Steps to reproduce
1. Create route containing multiple `(.*)*` patterns. For example `path: '/:seoPath(.*)*/c/:categoryId/:facetsPath(.*)*'`
2. Trigger processing of route containing the `(.*)*` pattern with a long path matching the pattern.
3. Observe a delay of seconds (~ 20 path segments) or minutes (~ 30 path segments)

This delay occurs when rendering `router-link` as well as during route navigation.

This fiddle has ~20 path segments and shows a 1-second delay when loading the page or clicking the link:
https://jsfiddle.net/zcrittendon/j1fmu680/2/

This fiddle has ~30 path segments and shows shows a multi-minute delay (or browser hang) when loading t...