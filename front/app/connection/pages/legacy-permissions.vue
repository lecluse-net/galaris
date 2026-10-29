<route lang="json">
{ "path": "/connection/permissions" }
</route>

<template><span /></template>
<script setup lang="ts">
import { definePage } from 'vue-router/experimental'
definePage({ redirect: to => ({ path: '/permissions', query: to.query, hash: to.hash }) })
</script>
