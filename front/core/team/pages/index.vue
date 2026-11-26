<template><span /></template>

<script setup lang="ts">
import { definePage } from 'vue-router/experimental'

definePage({
  redirect: to => ({ path: '/users', query: { ...to.query, tab: 'teams' }, hash: to.hash }),
})
</script>
