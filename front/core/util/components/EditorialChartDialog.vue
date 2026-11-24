<template>
  <q-dialog :model-value="true" :aria-label="dialogTitle" @update:model-value="open => { if (!open) emit('close') }">
    <q-card class="galaris-dialog-card editorial-chart-dialog">
      <DialogHeader :title="dialogTitle" />
      <q-card-section class="galaris-dialog-body editorial-chart-body">
        <div class="column q-gutter-sm">
          <q-select v-model="type" outlined dense :options="types" emit-value map-options :label="t('richEditor.chart.type')" />
          <q-input v-model="title" outlined dense :maxlength="maxChartTitle" :label="t('richEditor.chart.figureTitle')" />
          <div v-for="(row, index) in rows" :key="row.id" class="editorial-chart-row">
            <q-input v-model="row.label" outlined dense :maxlength="maxChartLabel"
              :label="t('richEditor.chart.label', { row: index + 1 })" />
            <q-input v-model="row.value" outlined dense inputmode="decimal" maxlength="24"
              :label="t('richEditor.chart.value', { row: index + 1 })" />
            <q-btn flat round dense color="negative" icon="close" :disable="rows.length === 1"
              :aria-label="t('richEditor.chart.removeRow', { row: index + 1 })" @click="rows.splice(index, 1)" />
          </div>
          <div>
            <q-btn outline dense color="primary" icon="add" :label="t('richEditor.chart.addRow')"
              :disable="rows.length >= maxChartRows" @click="addRow" />
          </div>
        </div>
        <div class="editorial-chart-preview">
          <img v-if="preview" :src="preview.image.src" :alt="preview.image.alt" />
          <div v-else-if="loadFailed" class="text-negative" role="alert">
            {{ t('richEditor.chart.renderFailed') }}
            <q-btn outline dense color="primary" :label="t('richEditor.chart.retry')" @click="loadRenderer" />
          </div>
          <q-spinner v-else-if="!renderer" :aria-label="t('richEditor.chart.loading')" role="status" />
          <div v-else-if="chart" class="text-negative" role="alert">{{ t('richEditor.chart.renderFailed') }}</div>
          <div v-else role="status">{{ t(type === 'pie' ? 'richEditor.chart.pieData' : 'richEditor.chart.numericData') }}</div>
        </div>
      </q-card-section>
      <q-separator />
      <q-card-actions align="right" class="galaris-dialog-actions q-pa-md">
        <q-btn outline color="primary" v-close-popup :label="t('common.cancel')" />
        <q-btn color="primary" :label="t('richEditor.apply')" :disable="!preview" @click="apply" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import DialogHeader from './DialogHeader.vue'
import { chartKinds, isEditorialChart, maxChartLabel, maxChartRows, maxChartTitle, type EditorialChart } from '../editorialChart'
import { svgImage } from '../editorialSvg'
import type { renderEditorialChart } from '../editorialChartRendering'

const { initial } = defineProps<{ initial: EditorialChart | null }>()
const emit = defineEmits<{ close: []; apply: [chart: EditorialChart, source: string] }>()
const { t } = useI18n()
const dialogTitle = computed(() => t(initial ? 'richEditor.chart.edit' : 'richEditor.chart.insert'))
const type = ref<EditorialChart['type']>(initial?.type ?? 'bar')
const types = computed(() => chartKinds.map(value => ({ value, label: t('richEditor.chart.' + value) })))
const title = ref(initial?.title ?? '')
const rows = ref(initial?.rows.map(({ label, value }, id) => ({ id, label, value: String(value) }))
  ?? [{ id: 0, label: '', value: '' }])
let nextRowId = rows.value.length
function addRow(): void {
  rows.value.push({ id: nextRowId++, label: '', value: '' })
}

const renderer = shallowRef<typeof renderEditorialChart>()
const loadFailed = ref(false)
async function loadRenderer(): Promise<void> {
  loadFailed.value = false
  try { renderer.value = (await import('../editorialChartRendering')).renderEditorialChart }
  catch { loadFailed.value = true }
}
onMounted(loadRenderer)

const chart = computed((): EditorialChart | null => {
  const data: EditorialChart = {
    version: 1,
    type: type.value,
    title: title.value.trim(),
    rows: rows.value.map(({ label, value }) => {
      const number = value.trim()
      return {
        label: label.trim(),
        value: /^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:e[+-]?\d+)?$/i.test(number) ? Number(number.replace(',', '.')) : NaN,
      }
    }),
  }
  return isEditorialChart(data) ? data : null
})
const preview = computed(() => {
  if (!chart.value || !renderer.value) return null
  try {
    const source = renderer.value(chart.value, t('richEditor.chart.' + type.value))
    const image = svgImage(document, source)
    return image ? { source, image } : null
  } catch {
    return null
  }
})
function apply(): void {
  if (chart.value && preview.value) emit('apply', chart.value, preview.value.source)
}
</script>

<style scoped>
.editorial-chart-dialog { width: 900px; max-width: 95vw; }
.editorial-chart-body { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 16px; align-items: start; align-content: start; }
.editorial-chart-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 0.65fr) auto; gap: 8px; align-items: center; }
.editorial-chart-preview { min-height: 120px; display: grid; place-items: center; padding: 8px; border-radius: 4px; background: var(--solaire-gray-light); }
.editorial-chart-preview img { width: 100%; height: auto; }
.body--dark .editorial-chart-preview { background: var(--solaire-gray-dark); }
@media (max-width: 1023px) {
  .editorial-chart-body { grid-template-columns: minmax(0, 1fr); }
}
</style>
