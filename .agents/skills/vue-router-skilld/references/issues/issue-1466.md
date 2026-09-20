---
number: 1466
title: useRoute is undefined when following vue-test-utils guide to test with Composition API
type: question
state: closed
created: 2022-07-10
url: "https://github.com/vuejs/router/issues/1466"
reactions: 7
comments: 11
labels: "[help wanted, external]"
---

# useRoute is undefined when following vue-test-utils guide to test with Composition API

### Version
```
>= 4.1.0
```

### Reproduction link
github.com







### Steps to reproduce
```
yarn
yarn test
```

### What is expected?
useRoute should be mocked and return the mocked value

### What is actually happening?
useRoute is undefined


---
When following the guide on vue-test-utils how to test vue-router with Composition API (see https://test-utils.vuejs.org/guide/advanced/vue-router.html#using-a-mocked-router-with-composition-api), the test fails.
The reason for that is that useRoute is undefined. The last version where it's working like described is 4.0.16.



---

## Top Comments

**@rros** (+14):

Yes, it seems related. We have this issue with version 4.1+ of vue-router. Using the latest version, the following mocks make the tests fail

```
vi.mock('vue-router', () => ({
  useRoute: () => ({
    query: { pageNumber: 1 },
  }),
}));
```

When changing the mocks like this, the tests will succeed again.
```
vi.mock('vue-router/dist/vue-router.mjs', () => ({
  useRoute: () => ({
    query: { pageNumber: 1 },
  }),
}));
```

So, the workaround is to mock the .mjs version until https://github.com/vitejs/vite/issues/8659 has been fixed

**@posva** [maintainer]:

I thought #1465 would fix this but it doesn't seem to affect it. It's as if vite or vitest was requiring a different vue-router module in `.vue` files and other `.ts` files. You might want to report this to vite/vitest team. 
I suspect this is yet, another cjs/esm misconfiguration on vue-router but I simply don't know what because I tried tracing which versions of vue-router are being imported and only `dist/vue-router.mjs` seems to be imported...

@patak-dev do you have any idea what might be happening here?
I tried creating a test in a `.ts` file and the mocking works just fine so someth...

**@Machineric** (+1):

> Yes, it seems related. We have this issue with version 4.1+ of vue-router. Using the latest version, the following mocks make the tests fail
> 
> ```
> vi.mock('vue-router', () => ({
>   useRoute: () => ({
>     query: { pageNumber: 1 },
>   }),
> }));
> ```
> 
> When changing the mocks like this, the tests will succeed again.
> 
> ```
> vi.mock('vue-router/dist/vue-router.mjs', () => ({
>   useRoute: () => ({
>     query: { pageNumber: 1 },
>   }),
> }));
> ```
> 
> So, the workaround is to mock the .mjs version until [vitejs/vite#8659](https://github.com/vitejs/vite/iss...