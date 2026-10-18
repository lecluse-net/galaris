<template><GraphicReference /></template>
<script setup lang="ts">
import { onBeforeUnmount } from 'vue'
import { settings } from '@/core/settings'
import GraphicReference from '@/app/index/pages/graphic-reference.vue'
const { environment = 'dev' } = defineProps<{ environment?: string }>()
// Only this isolated test host injects the application environment.
const previous = settings.APP_ENV
Object.assign(settings, { APP_ENV: environment })
onBeforeUnmount(() => Object.assign(settings, { APP_ENV: previous }))
</script>
