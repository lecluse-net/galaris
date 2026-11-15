<template><PageHeader v-if="title" icon="description" :title="title" /></template>
<script setup lang="ts">
import { useMeta } from 'quasar'
import { usePageTitle } from '@/core/navigation'
import PageHeader from '@/core/util/components/PageHeader.vue'
defineProps<{ title?: string }>()
useMeta({ title: 'Galaris' })
usePageTitle()
</script>
