---
number: 2473
title: Is there any way to prevent meta data from being automatically merged?
category: Help and Questions
created: 2025-03-06
url: "https://github.com/vuejs/router/discussions/2473"
upvotes: 1
comments: 1
answered: true
---

# Is there any way to prevent meta data from being automatically merged?

<img width="747" alt="image" src="https://github.com/user-attachments/assets/955ac1bb-1bd9-4748-a7e9-1c35b9ed885c" />


---

## Accepted Answer

**@posva** [maintainer]:

You can still access the original records `meta` in the array of `matched`: `matched.map(r => r.meta)`