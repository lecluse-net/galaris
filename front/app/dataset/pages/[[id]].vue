<template><span /></template>
<script setup lang="ts">
import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
const route = useRoute(), router = useRouter()
watch(() => route.params.id, id => { void router.replace({ path: '/documents', query: id ? { document_id: String(id) } : { type: 'data' } }) }, { immediate: true })
</script>
