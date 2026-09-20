<template>
  <div class="execution-date-filters">
    <q-input
      :model-value="dateFrom"
      type="date"
      outlined
      dense
      clearable
      stack-label
      :label="t('executionMonitoring.dateRange.from')"
      :max="dateTo || undefined"
      class="execution-date-filters__input"
      @update:model-value="setDateFrom"
    />
    <q-input
      :model-value="dateTo"
      type="date"
      outlined
      dense
      clearable
      stack-label
      :label="t('executionMonitoring.dateRange.to')"
      :min="dateFrom || undefined"
      class="execution-date-filters__input"
      @update:model-value="setDateTo"
    />
    <q-btn
      v-if="dateFrom || dateTo"
      flat
      round
      dense
      icon="filter_alt_off"
      color="grey-7"
      :aria-label="t('executionMonitoring.dateRange.clear')"
      @click="clear"
    >
      <q-tooltip>{{ t('executionMonitoring.dateRange.clear') }}</q-tooltip>
    </q-btn>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const dateFrom = defineModel<string | null>('dateFrom', { default: null })
const dateTo = defineModel<string | null>('dateTo', { default: null })
const emit = defineEmits<{ change: [] }>()
const { t } = useI18n()

function normalize(value: string | number | null): string | null {
  return typeof value === 'string' && value ? value : null
}

function setDateFrom(value: string | number | null): void {
  dateFrom.value = normalize(value)
  emit('change')
}

function setDateTo(value: string | number | null): void {
  dateTo.value = normalize(value)
  emit('change')
}

function clear(): void {
  dateFrom.value = null
  dateTo.value = null
  emit('change')
}

</script>

<style scoped>
.execution-date-filters {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}

.execution-date-filters__input {
  width: 136px;
}

@media (max-width: 600px) {
  .execution-date-filters {
    flex: 1 1 100%;
    flex-wrap: wrap;
    width: 100%;
  }

  .execution-date-filters__input {
    flex: 1 1 140px;
    width: auto;
  }
}
</style>
