---
number: 2442
title: How to figure out what is causing the `invalid param(s)` warn to trigger
category: Help and Questions
created: 2025-01-23
url: "https://github.com/vuejs/router/discussions/2442"
upvotes: 1
comments: 1
answered: true
---

# How to figure out what is causing the `invalid param(s)` warn to trigger

Good morning!

I do have started to see my logs filled with a 
`[Vue Router warn]: Discarded invalid param(s) "" when navigating. See https://github.com/vuejs/router/blob/main/packages/router/CHANGELOG.md#414-2022-08-22 for more details.` warn message.

Problem is that the invalid param is `""`, which is not helpful at all. Also, no way of logging the file/function that si causing the error, or even the route. 

Is there a way for me to figure out what is causing the problem?


---

## Accepted Answer

**@posva** [maintainer]:

It's a warn so you can check the stack trace, add a debugger break point and find the relevant part of your code that triggered the issue