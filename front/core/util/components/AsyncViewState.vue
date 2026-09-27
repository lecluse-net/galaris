<template>
  <div class="async-view-state q-pa-md" :role="failed ? 'alert' : 'status'" :aria-busy="!failed">
    <template v-if="failed">
      <span>{{ $t('common.viewLoadError') }}</span>
      <q-btn flat color="primary" icon="refresh" :label="$t('common.retry')" @click="$emit('retry')" />
    </template>
    <template v-else>
      <q-spinner color="primary" size="24px" aria-hidden="true" />
      <span>{{ $t('common.loading') }}</span>
    </template>
  </div>
</template>

<script setup lang="ts">
defineProps<{ failed: boolean }>()
defineEmits<{ retry: [] }>()
</script>

<style scoped>
.async-view-state {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 80px;
}
</style>
