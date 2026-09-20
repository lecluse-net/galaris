---
number: 2472
title: 路径参数和固定路由冲突，现有解决方案吗？
category: Help and Questions
created: 2025-03-05
url: "https://github.com/vuejs/router/discussions/2472"
upvotes: 1
comments: 3
answered: true
---

# 路径参数和固定路由冲突，现有解决方案吗？

```
/inventory/orderDispatch/1000             是动态路由，1000是参数
/inventory/orderDispatch/procurement      是固定的路由
```

结果 `/inventory/orderDispatch/procurement`   也跳向了` /inventory/orderDispatch/1000` 页面。`procurement`成参数了

这有解决方案吗？




---

## Accepted Answer

**@posva** [maintainer]:

For your info, in Vue Router 4, the order does not matter