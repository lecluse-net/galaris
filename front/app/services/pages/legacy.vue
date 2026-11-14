<template><div /></template>
<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
const route = useRoute(), router = useRouter()
void router.replace({ path: '/services', query: route.query, hash: route.hash })
</script>
<route lang="json">{ "path": "/tools" }</route>
