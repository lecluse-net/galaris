<template>
  <div class="graph-view-controls row items-center q-gutter-xs no-wrap">
    <slot />
  </div>
</template>

<style scoped>
.graph-view-controls {
  padding: 3px;
  border-radius: 999px;
  background: var(--solaire-blue-light);
}

.body--dark .graph-view-controls {
  background: var(--solaire-blue-dark);
}
</style>
