---
number: 1586
title: Questions about the catch all syntax
type: docs
state: open
created: 2022-10-21
url: "https://github.com/vuejs/router/issues/1586"
reactions: 2
comments: 1
labels: "[docs]"
---

# Questions about the catch all syntax

### What problem does this feature solve?
The documentation regarding catch-all routes can be improved.  Specifically the section describing why the catch all parameter should be repeatable. Also, the suggested example parameter name "pathMatch" is a little generic and confusing.  The term does not build any immediate intuition for people coming into a new project that the route is a catch all.

### What does the proposed API look like?

##### Improving "pathMatch" example parameter

I'm sure others have better ideas to improve "pathMatch" as the suggested catch all parameter name.  "Match" is implied because it wouldn't be captured if it wasn't a match, so I suggest "Match" be removed. To make it more clear we could use "completePath", "catchAllPath", "anyPath" or even just "path" ...