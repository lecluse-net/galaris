---
number: 2437
title: RouterView with Transition leads to memory leak and detached nodes
type: other
state: closed
created: 2025-01-13
url: "https://github.com/vuejs/router/issues/2437"
reactions: 6
comments: 3
labels: "[external]"
---

# RouterView with Transition leads to memory leak and detached nodes

### Reproduction

https://play.vuejs.org/#eNq9Vl1v2zYU/SuE+mAHiyQ3LfqguUXaIUA2rMvQZXuZ9kBLtM1EIgmSUhwY/u87JPXl1AnQhzaBE+l+HJ57eC/pfVRTLpI7E2URr5XUluxJoRm17KNS5EDWWtZk1jZsloshQMvGMj14kzQYxhCX2/uoUknIz8WAPMfnLBeEJI1h85Ae3mvZCDufvULa7Cw6j7p08FuaQnNliWG2UaSiYvM+j6zJow8Tal881D+cPUzJxwPBZRpQkIMXy2pVgRHeCFlOctvYVNICf09+kcAWTFhy8EsR/CxvNRWGWy4FEbRmCFzTkg1+RBRDWsYN/ANMHpG0h0lHnEAhHTnAsEwnBPFq7GPlHhO3WAwspmNaWN6y895YMdqyzkj2DtMOS2REKlpw+0guFova/JyLw/NpSvZJdGVkBVYh/nh1p/CTta0MAN1aGVmERCjf0ceuhv1I7Im++8xqqR+vubH4d94Zgyynt3TY/WtZM797fev1hq7/+uZcIfMobrAMjcp2PrSQwti+3d8fcZn7IreBZnaK+/wMypCQbTLyb9jzPVHUbjMyS2corm+KbCR/8FnTQOroHUePNYTw//D3gAGCtNOiv21qfufi/pTE2L+XxqbkLeElUK9vPl+NIzLBtBLeUAb8nnvf6c7fZwCoH582XkuNJC5KtiNckNeLxSKPend2zx57b28dRu+aVZX0epL9HrkO4YAGDBOHRbpRC09PZsxLeNQPP1bDj59u/r59QUS4XGXfXT4vwTfrB+2CHnFNFW4VKaCeHxSs5h0QLQvng7ONAjlzHm2tVSZL00ao+02Cfk/HiMu3yZtkgVWNnVgTZup4peWDwfMd0LvpyaNLBKUla62UlYmp4s8t8VXg5bvkXfI6rfgqBXrqFfDYDhpCHFCmNTgb1nzzpEg3orxi+ka5s/O4WApdH37zNqsbd2QHe7Flxf0J+53B5jjKf2qG6lpcL4PPUr1hGCbnvvrrD7bD8+CsZdlUiH7B+YX5Mx0cQ9inRpSgPYnzbH/1e8bF5tZc7SzDPdIV5Yh6NXy830h3wT1X+kj3TfJ2oqK/EUxSGHcPCNqeE/d1JOStpC6ZzsiF2hGQ5SV5hSbGHBEE6Q0X8UpaK+sMza123q5oWYLsYPHXFWDJB0LJT/h44C67YmscpNPI7cV05RF+JFAUxYQArjb8XnQI0eF/Sb4hbg==

### Steps to reproduce the bug

...

---

## Top Comments

**@acordy** (+3):

I've spent the last few hours testing this in various ways with the Nightly build of Chrome. A fix was made and merged on January 10, 2025 (discussed here).

I am no longer able to reproduce the issue in that build. So, it would seem that this was indeed a Chrome bug that will eventually make its way into the stable build.

...

**@edison1105** [maintainer]:

Similar to https://github.com/vuejs/core/issues/12306
I think this is a Chrome bug. I can't reproduce it using Chrome v128, but it happens in Chrome v131.



**@posva** [maintainer]:

Thanks a lot for taking a deeper look into this @acordy and @edison1105  