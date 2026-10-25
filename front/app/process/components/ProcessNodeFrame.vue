<template>
  <svg class="node-frame" aria-hidden="true" focusable="false">
    <rect width="100%" height="100%" :rx="radius" />
  </svg>
</template>

<script setup lang="ts">
defineProps<{ radius: number }>()
</script>

<style scoped>
/* CSS borders snap fractional widths to device pixels before the board is scaled.
   An SVG stroke preserves the reference's 1.5 / 2 / 2.2 widths at every zoom. */
.node-frame { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; pointer-events: none; fill: none; stroke: var(--node-accent); stroke-width: var(--node-border-width); }
</style>
