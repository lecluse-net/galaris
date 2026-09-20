---
number: 1535
title: Allow accessing history state from Route-objects
type: feature
state: open
created: 2022-08-26
url: "https://github.com/vuejs/router/issues/1535"
reactions: 7
comments: 7
labels: "[enhancement, discussion]"
---

# Allow accessing history state from Route-objects

While I was refactoring my code to remove *artificial* params in lieu of the 4.1.4 release to write my data to the `history.state` object, I noticed that I can pass a `state` property to `$router.push()` and was kind of surprised that I could not retrieve it with `$route.state` (like I can with queries or params) but had to access it using `window.history.state`.

Would it be possible to implement a `state` property containing only the passed state in the `RouteLocationNormalizedLoaded` interface?

That would make it a more intuitive replacement for the removed artificial params IMO.

---

## Top Comments

**@posva** [maintainer] (+3):

`history.state` has a few limitations and I'm still not sure it can be included in all locations. For example, it cannot be included in `to` locations in navigation guards, so, unfortunately, it cannot be added to any existing `RouteLocation...`. This would need yet another route location type variant.

Note that right now this can be achieved with a guard:

```js
router.afterEach(to => {
  to.state = history.state
})
```

but there are other alternatives like a composable `useHistoryState()`:

```ts
import { shallowRef, onScopeDispose } from 'vue'

function useHistoryState<T = unknown>(router?: Router) {
  const state = shallowRef<T>(history.state)
  const remove = (router || useRouter()).afterEach(() => {
    state.value = history.state
  })
  onScopeDispose(remove)
  return state
}
```...

**@AlexandreBonaventure** (+7):

Yes, I appreciate you are providing migration steps, but going back to my specific use-case I don't see any alternatives working for me:
- _Putting the data in a store_: does not feel right because that's really not a global state
- _Move the data to an actual param_: not relevant either because that's not a URL-based state
- _Pass the data as state to save it to the History API state_: as per this conversation is not fitting the use-case
- _Pass it as a new property to `to.meta` during navigation guards_: does not seem to work for me because I can't set the meta when pushing the navigatio...

**@posva** [maintainer]:

@AlexandreBonaventure alternatives are in the changelog