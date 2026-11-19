<template>
  <DocumentReferenceToolbar v-if="toolbar" v-bind="$attrs" mode="card"><slot /></DocumentReferenceToolbar>
  <ResourceEmbed v-else-if="display === 'card'" v-bind="$attrs" :title="title" display="card" />
  <ResourcePreviewBlock v-else v-bind="$attrs" :title="title" :open-label="openLabel || title">
    <template v-if="$slots.preview" #preview><slot name="preview" /></template>
    <template v-if="$slots.actions" #actions><slot name="actions" /></template>
  </ResourcePreviewBlock>
</template>
<script setup lang="ts">
import DocumentReferenceToolbar from './DocumentReferenceToolbar.vue'
import ResourcePreviewBlock from './ResourcePreviewBlock.vue'
import { ResourceEmbed } from '../resourceEmbed'

defineOptions({ inheritAttrs: false })
const { title = '' } = defineProps<{ toolbar?: boolean; display?: 'card'; title?: string; openLabel?: string }>()
</script>
