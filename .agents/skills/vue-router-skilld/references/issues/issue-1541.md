---
number: 1541
title: Can we add 'href' as property to the type for Router.currentRoute
type: other
state: closed
created: 2022-08-31
url: "https://github.com/vuejs/router/issues/1541"
reactions: 4
comments: 3
---

# Can we add 'href' as property to the type for Router.currentRoute

### What problem does this feature solve?
the `currentRoute` value is initially defined without `href` property (from `START_LOCATION_NORMALIZED`) but on Router.install() it is immediately overwritten with an object that ultimately comes from router.resolve() (which has return type `RouteLocation & { href: string }`.
So it appears to me that `currentRoute` (at runtime) almost always has the `href` property - which helps tremendously when composing urls in your application and working with a base other than `/` (e.g. to copy a complete and valid url to the clipboard).

Due to the fact that the initial value doesn't have `href` prop, one could ether make the `href` prop optional (in type definition) or extend `START_LOCATION_NORMALIZED` to have a `href` property (with initial value from ...

---

## Top Comments

**@posva** [maintainer]:

The lack of `href` is intended as it's only used in very specific places within the router code.

> which helps tremendously when composing urls in your application and working with a base other than / (e.g. to copy a complete and valid url to the clipboard).

What do you mean? Do you have concrete examples? Isn't `router.resolve()` all you need?

**@benkroeger**:

This is what the currentRoute looks like immediately after app initialization with `base = '/foo/'` and route `/question/:id`:






**@benkroeger**:

The ultimate goal is to receive the current URL from the browser (incl. origin) and overwrite the `hash` property.

You're right. This can be done with `router.resolve()`. Here is how I did it:

```ts
import { type RouteQueryAndHash, useRoute, useRouter } from 'vue-router';
const router = useRouter();
const currentRoute = useRoute();

const getCurrentRouteAsURL = (overrides: RouteQueryAndHash = {}) => 
  new URL(router.resolve({ ...currentRoute, ...overrides }).href, window.location.origin);
```

thanks for the hint.