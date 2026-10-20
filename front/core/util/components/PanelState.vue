<template>
  <div class="panel-state" :class="state === 'error' ? 'text-negative' : 'text-grey-7'"
    :role="state === 'error' ? 'alert' : 'status'" :aria-busy="state === 'loading'">
    <q-spinner v-if="state === 'loading'" color="primary" size="28px" />
    <q-icon v-else :name="icon || icons[state]" size="28px" />
    <span>{{ message || (state === 'loading' ? t('common.loading') : '') }}</span>
    <q-btn v-if="state === 'error' && retryLabel" outline dense color="negative" :label="retryLabel" @click="emit('retry')" />
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineProps<{
  state: 'loading' | 'empty' | 'forbidden' | 'error'
  message?: string
  icon?: string
  retryLabel?: string
}>()
const emit = defineEmits<{ retry: [] }>()
const { t } = useI18n()
const icons = { empty: 'inbox', forbidden: 'lock', error: 'warning' }
</script>

<style scoped>
.panel-state {
  display: flex;
  min-height: 120px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 8px;
  padding: 18px;
  text-align: center;
  font-size: .78rem;
}
</style>
