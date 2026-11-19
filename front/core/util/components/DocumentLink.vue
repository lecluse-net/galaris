<template>
  <DocumentReferenceToolbar v-if="toolbar" v-bind="$attrs" mode="link"><slot /></DocumentReferenceToolbar>
  <a v-else v-bind="$attrs"><q-icon v-if="icon" :name="icon" aria-hidden="true" /><slot /></a>
</template>
<script setup lang="ts">
import DocumentReferenceToolbar from './DocumentReferenceToolbar.vue'

defineOptions({ inheritAttrs: false })
defineProps<{ toolbar?: boolean; icon?: string }>()
</script>
