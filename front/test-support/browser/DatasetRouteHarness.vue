<template><RouterView /></template>

<script setup lang="ts">
import { onScopeDispose } from 'vue'
import { RouterView, useRouter } from 'vue-router'
import DatasetLibrary from '../../app/dataset/pages/[[id]].vue'

// Mount the actual route so descendant editor guards run during native traversal.
const router = useRouter()
const remove = router.addRoute({ path: '/dataset/:id?', component: DatasetLibrary })
const route = router.currentRoute.value
void router.replace({ path: route.path, query: route.query, hash: route.hash, force: true })
onScopeDispose(remove)
</script>
