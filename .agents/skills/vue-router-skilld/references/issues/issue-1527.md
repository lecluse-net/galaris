---
number: 1527
title: route.params are lost
type: other
state: closed
created: 2022-08-23
url: "https://github.com/vuejs/router/issues/1527"
reactions: 7
comments: 26
---

# route.params are lost

### Version
4.1.4

### Reproduction link
jsfiddle.net/posva/3yq6ojLv







### Steps to reproduce
//list component
 import { useRouter } from 'vue-router';
  const router = useRouter();
   router.push({
                name: 'detail',
                params:{data:'111'}
});
// detail
import { useRoute } from 'vue-router';
const route = useRoute();
// route.params  -> {}

### What is expected?
route.params -> {data:'111'}

### What is actually happening?
route.params -> {}



---

## Top Comments

**@posva** [maintainer] (+3):

This is mentioned in the changelog: https://github.com/vuejs/router/blob/main/packages/router/CHANGELOG.md#414-2022-08-22

**@geedys** (+1):

> > > 大佬, 我也遇到这个问题了, vue router 版本是 4.0.12, 更新到 4.0.x 的其他版本也不能使用
> > 
> > 
> > 4.1.3 之前我没有遇到这个问题.今天更新到4.1.4就有问题. 我路由注册时使用的 props:true方式,path上没有变量定义. 最终导致目标路由组件无法接收动态传入的参数..
> 
> 部署后出现了这个问题, 本地开发没问题, 于是在本地测试重新装了 node_modules, 之后本地也出现这个问题了, 切换其他 4.0.x 的版本也是同样的问题, 请问大佬有解决方案吗!!!

暂时没有解决方案,我跟踪4.1.4源码,似乎必须要将参数在path中定义或者明确在props中定义(path中不定义参数,props:true这种方式就会导致这样的错误),但这都不满足我的需求, 我暂时还是回退到4.1.3了 

**@ShuaiNingZ**:

大佬, 我也遇到这个问题了, vue router 版本是 4.0.12, 更新到 4.0.x 的其他版本也不能使用