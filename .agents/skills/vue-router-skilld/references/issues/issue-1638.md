---
number: 1638
title: slashes should not be encoded for catch all regexes
type: bug
state: open
created: 2022-12-20
url: "https://github.com/vuejs/router/issues/1638"
reactions: 2
comments: 10
labels: "[bug,  breaking change]"
---

# slashes should not be encoded for catch all regexes

### Version
4.1.6

### Reproduction link
codesandbox.io







### Steps to reproduce
1. Load the codesandbox.io project using the link provided.
2. Click on About page.
3. Click on the "Add hash" button, this will call `router.replace({ hash: '#something' })`.
4. Notice that vue-router correctly appends the # in the url. `(https://domain.com/about.html#yippy)`.
5. Click on Deep About page.
6. Click on the "Add hash" button.
7. Notice that the url becomes `https://domain.com/test%2Fdeep%2Fabout.html#yaya`.


### What is expected?
Url to become `https://domain.com/test/deep/about.html#yaya`

### What is actually happening?
Url became `https://domain.com/test%2Fdeep%2Fabout.html#yaya`

![image]...