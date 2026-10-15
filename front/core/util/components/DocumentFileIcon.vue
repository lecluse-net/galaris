<template>
  <svg class="galaris-document-file-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false" :style="{ width: size, height: size }"
    fill="none" stroke="var(--solaire-gray-accent)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
    <path class="document-paper" d="M6 2h8l6 6v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z" />
    <path fill="var(--solaire-gray-accent)" fill-opacity="0.15" d="M14 2v4a2 2 0 0 0 2 2h4Z" />
    <path d="M8 11h8M8 14h8M8 17h5" />
  </svg>
</template>

<script setup lang="ts">
const { size = '24px' } = defineProps<{ size?: string }>()
</script>

<style scoped>
.galaris-document-file-icon { display: inline-block; flex: none; vertical-align: middle; }
.document-paper { fill: var(--solaire-gray-light); }
:global(body.body--dark) .document-paper { fill: var(--solaire-gray-dark); }
</style>
