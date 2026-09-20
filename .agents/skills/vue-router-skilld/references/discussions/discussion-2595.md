---
number: 2595
title: Wikipedia-like route matching
category: Help and Questions
created: 2025-12-17
url: "https://github.com/vuejs/router/discussions/2595"
upvotes: 1
comments: 1
answered: true
---

# Wikipedia-like route matching

A year ago I posted this question on stackoverflow looking for advice on how to accomplish a Wikipedia-like parsing of the path.
In short: I wanted a rule that when navigating to `/foo` it would set the params `{ namespace: '', page: 'foo' }`, and when navigating to `/bar:baz` it would set `{ namespace: 'bar', page: 'baz' }` instead.

The answers I got were unpleasant, they felt like a hack and I ended up abandoning vue for that project altogether.
This situation becomes even more frustrating when you consider something like `/:namespace-:page` works just fine, except I cannot use a colon there, which is exactly what I needed. 

One year later I am revisiting this topic and I wonder if somethin...

---

## Accepted Answer

**@posva** [maintainer]:

You can do this

- `/:namespace(?:([^/]+\):)?:pagename(.*)` the `()` after a parameter allows you to put a custom regex. The closing `)` needs o be escaped so it's not considered the end of the outer parentheses pair