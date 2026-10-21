<template><LibraryIcon :icon="icon" :size="size" :expanded="expanded" :default-icon="defaultIcon" /></template>
<script setup lang="ts">
import { LibraryIcon } from '@/core/util'
defineProps<{ icon?: string | null; size?: string; expanded?: boolean; defaultIcon?: string }>()
</script>
