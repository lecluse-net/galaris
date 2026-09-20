---
number: 1411
title: Smooth scrolling does not work in firefox but does in chrome
type: bug
state: open
created: 2022-05-19
url: "https://github.com/vuejs/router/issues/1411"
reactions: 1
comments: 2
labels: "[bug, has workaround, browser quirk]"
---

# Smooth scrolling does not work in firefox but does in chrome

### Version
4.0.15

### Reproduction link
github.com







### Steps to reproduce
Run the reproduction scroll down and press the `link` titled link.

### What is expected?
It is expected that the current page is changed to the `test` page and is smoothly scrolled to the top.

### What is actually happening?
In firefox the current page switches to the `test` page, but does not scroll up.

---
Works in chrome. Removing the `behavior: 'smooth'` makes the `test` page at least start on top, but also removes the intended scroll effect.

