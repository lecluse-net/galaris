<template><LibrarySplitterHandle :horizontal="horizontal" /></template>
<script setup lang="ts">
import { LibrarySplitterHandle } from '@/core/util'
defineProps<{ horizontal?: boolean }>()
</script>
