<template><RouterView /></template>

<script setup lang="ts">
import { onScopeDispose } from 'vue'
import { RouterView, useRouter } from 'vue-router'
import Files from '../../app/file_share/pages/index.vue'

// Exercise native history with the real route and its descendant editor guards.
const router = useRouter()
const remove = router.addRoute({ path: '/files', component: Files })
const route = router.currentRoute.value
void router.replace({ path: route.path, query: route.query, hash: route.hash, force: true })
onScopeDispose(remove)
</script>
