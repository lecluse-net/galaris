<template>
  <span class="inline-flex">
    <q-btn v-bind="$attrs" :aria-label="label"><slot /></q-btn>
    <q-tooltip v-if="!noTooltip">{{ label }}</q-tooltip>
  </span>
</template>
<script setup lang="ts">
defineOptions({ inheritAttrs: false })
defineProps<{ label: string; noTooltip?: boolean }>()
</script>
