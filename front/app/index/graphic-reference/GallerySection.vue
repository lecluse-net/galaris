<template>
  <section class="gallery-section">
    <div class="section-heading row items-center q-mb-md">
      <q-icon :name="icon" color="primary" size="22px" aria-hidden="true" />
      <h2 class="text-h6 q-ma-none">{{ title }}</h2>
    </div>
    <slot />
  </section>
</template>
<script setup lang="ts">
defineProps<{ title: string; icon: string }>()
</script>
<style scoped>
.gallery-section { min-width: 0; padding: 20px; border: 1px solid color-mix(in srgb, currentColor 16%, transparent); border-radius: 8px; scroll-margin-top: 80px; }
.section-heading { gap: 8px; }
</style>
