<template>
  <span class="document-splitter-handle" :class="{ 'document-splitter-handle--horizontal': horizontal }">
    <q-icon name="drag_indicator" size="16px" />
  </span>
</template>
<script setup lang="ts">
defineProps<{ horizontal?: boolean }>()
</script>
<style scoped>
.document-splitter-handle { display: flex; width: 20px; height: 42px; align-items: center; justify-content: center; border: 1px solid color-mix(in srgb, currentColor 18%, transparent); border-radius: 10px; color: var(--solaire-gray-accent); background: var(--q-card-background, #fff); box-shadow: 0 2px 8px rgba(35, 46, 66, .12); }
.document-splitter-handle--horizontal { width: 42px; height: 20px; }
.document-splitter-handle--horizontal .q-icon { transform: rotate(90deg); }
.document-splitter-handle:hover, .document-splitter-handle:focus-visible { color: var(--solaire-blue-accent); }
.document-splitter-handle:focus-visible { outline: 2px solid var(--solaire-blue-accent); }
:global(body.body--dark) .document-splitter-handle { background: var(--q-dark-page); box-shadow: 0 2px 8px rgba(0, 0, 0, .38); }
</style>
