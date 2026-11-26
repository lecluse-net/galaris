<template>
  <nav v-if="total > Math.min(50, pageSize)" :aria-label="label" class="home-pagination">
    <q-pagination :model-value="page" :max="Math.ceil(total / pageSize)" :max-pages="5" direction-links
      :disable="loading" @update:model-value="emit('update:page', $event)" />
    <q-select :model-value="pageSize" :options="[10, 20, 50, 100, 500]" :label="pageSizeLabel"
      dense outlined :disable="loading" class="home-page-size" @update:model-value="emit('update:pageSize', $event)" />
  </nav>
</template>

<script setup lang="ts">
defineProps<{ total: number; page: number; pageSize: number; loading: boolean; label: string; pageSizeLabel: string }>()
const emit = defineEmits<{ 'update:page': [value: number]; 'update:pageSize': [value: number] }>()
</script>

<style scoped>
.home-pagination { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 16px; margin-top: 20px; }
.home-page-size { min-width: 110px; }
</style>
