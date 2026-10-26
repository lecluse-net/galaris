<route lang="json">
{ "path": "/documents/folders/:id" }
</route>
<template><q-page><DocumentFolderCollection :key="id" :folder-id="id" /></q-page></template>
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import DocumentFolderCollection from '../../components/DocumentFolderCollection.vue'
const route = useRoute()
const id = computed(() => String(route.params.id ?? ''))
</script>
