---
number: 2469
title: How to get the domain of the last page in the Vue Router history?
category: Help and Questions
created: 2025-03-02
url: "https://github.com/vuejs/router/discussions/2469"
upvotes: 1
comments: 1
answered: true
---

# How to get the domain of the last page in the Vue Router history?

What I am trying to achieve is to implement a custom back button, that checks the previously visited page from the Router History, and if the page is within my own application (same domain name), it should use router.back(), but if the page is outside of mine (other domain or nonexistent, user entered url directly, etc...) then it should navigate to my homepage instead.

To do that, I need to know the domain of the last history entry. The router itself only provides the part AFTER the domain and document.referrer is always empty.

I also cannot manually store the last page because it would either only work once, or if it was a stack, it would get messed up when using router.back().

How am i supposed to get the domain from the history when document.referrer and router.history almost ...

---

## Accepted Answer

@HerrNamenlos123  Please try using the following methods to execute different logic based on whether the `back` has a value:

```ts
const router = useRouter()
const goBack = () => {
  const { back } = router.options.history.state

  if (back) {
    router.go(-1)
    return
  }

  // Otherwise, go to other page...
}
```