<template><span /></template>

<script setup lang="ts">
import { definePage } from 'vue-router/experimental'

definePage({
  redirect: to => ({ path: '/users', query: { ...to.query, tab: to.query.tab ?? 'roles' }, hash: to.hash }),
})
</script>
