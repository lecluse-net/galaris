---
number: 454
title: Component guards not working when defined on mixins
type: question
state: open
created: 2020-09-07
url: "https://github.com/vuejs/router/issues/454"
reactions: 45
comments: 24
labels: "[help wanted, external]"
---

# Component guards not working when defined on mixins

### Version
4.0.0-beta.9

### Reproduction link
https://jsfiddle.net/ukeagtjm/







### Steps to reproduce
    const Mixin = {
        beforeRouteEnter(to, from, next) {
            console.log('****** Before route enter (mixin)');
            next();
        }
    };

...

    mixins:[Mixin]

### What is expected?
beforeRouteEnter() to run and log from mixin

### What is actually happening?
beforeRouteEnter() is never executed



---

## Top Comments

**@LinusBorg** [maintainer] (+4):

@dpmango That's not supposed to work. Route guards only work when used in route components, not just any components.

**@posva** [maintainer]:

It wasn't intentionally removed but I will have to check a way to apply the mixins from components and its `extends` option

**@TothingWay** (+5):

Will the problem be fixed?