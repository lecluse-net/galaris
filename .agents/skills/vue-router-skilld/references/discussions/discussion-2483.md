---
number: 2483
title: Double Encoding of Query Parameters
category: Help and Questions
created: 2025-03-24
url: "https://github.com/vuejs/router/discussions/2483"
upvotes: 1
comments: 2
answered: true
---

# Double Encoding of Query Parameters

### Reproduction

https://stackblitz.com/edit/vitejs-vite-qjvsopux

### Steps to reproduce the bug

### Description
When pushing a query using the `vue-router`, I've observed inconsistent encoding behavior: query parameters are either encoded twice or not at all. 

### Example
Consider the following code snippet:

```javascript
const router = useRouter();

router.push({
  query: { notEncoded: '{name}', encoded: encodeURIComponent('{name}') },
});
```

The resulting URL appears as:

```
/?notEncoded={name}&encoded=%257Bname%257D
```

-  The `notEncoded` parameter remains unchanged, as expected.
-  The `encoded` parameter, however, is encoded twice. 

For reference, the expected single encoding result is:

```javascript
console.log(encodeURIComponent('{name}')); // %7Bname%7D
```

...

---

## Accepted Answer

**@posva** [maintainer]:

You must pass `params`, `query`, and `hash` unencoded because the router handles them. If you follow that rule, it will work out