---
number: 2495
title: Add static part before optional parameter?
category: Help and Questions
created: 2025-04-21
url: "https://github.com/vuejs/router/discussions/2495"
upvotes: 1
comments: 1
answered: true
---

# Add static part before optional parameter?

I've been trying to come up with a way to have an optional parameter proceeded by an identifying static part.  e.g.
```js
{ path: '/a/:a/b?/:b?' }
```
What I'm after is for `/a/123` and `/a/123/b/456` to point to the same route, without having to duplicate the route definition.  Is there any way to achieve this?  Also, I would need to be able to navigate to the static part of the route with `{ name: 'my.route.name', params: { a: 123, b: 456 } }`.  I have a whole series of routes that I need to add this optional parameter to, and I don't want to have to repeat the route definition for them all.  Note that `/a/123/b` should *not* be valid in this case.

Thanks!

---

## Accepted Answer

**@posva** [maintainer]:

Adding an alias without the parameter should work