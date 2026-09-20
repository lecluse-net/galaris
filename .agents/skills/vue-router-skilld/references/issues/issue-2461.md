---
number: 2461
title: onBeforeRouteUpdate to also run on beforeCreate
type: other
state: closed
created: 2025-02-13
url: "https://github.com/vuejs/router/issues/2461"
reactions: 18
comments: 6
---

# onBeforeRouteUpdate to also run on beforeCreate

### What problem is this solving

many times I encountered code that looked like a higher order component for a group of pages that only available for specific permission / payment / role / something:

```
<script setup>

const auth = useAuth();
const router = useRouter();
const route = useRoute();

if (!hasPermission(auth.user, route.name)) {
  router.push('somewhere-else')
}

onBeforeRouteUpdate((to, from, next) => { 
  if (!hasPermission(auth.user, to.name)) {
    next('somewhere-else')
  }
})

</script>
```

You can probably notice the code duplication here that has the same purpose.
That duplication forces developers to use both `useRouter` and `useRoute` compositions, and also the `onBeforeRouteUpdate` lifecycle hook.

### Proposed solution

a solution similar to watch immediate.
```
<script setup>

const auth = useAuth();

onBeforeRouteUpdate((to, from, next) => { 
  if (!hasPermission(auth.user, to.name)) {
    next('somewhere-else')
  }
}, { immediate: true })

</script>
```

### Describe alternatives you've considered

_No response_

---

## Top Comments

**@adirkandel** (+3):

Good point! I also encountered the same repetitive pattern.

**@posva** [maintainer]:

As pointed out before, this is not technically possible because the composable would execute after the navigation is finished 

**@posva** [maintainer]:

The comments are concerning… it’s looks like AI spam so I will lock this