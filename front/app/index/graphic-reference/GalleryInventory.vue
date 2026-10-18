<template>
  <p>{{ t('graphicReference.glyphHint') }}</p>
  <div class="row q-gutter-md items-center q-mb-md">
    <q-select v-model="family" :options="families" emit-value map-options outlined dense :label="t('graphicReference.glyphs')" class="family-select" />
    <q-input v-model="filter" outlined dense clearable :label="t('graphicReference.search')"><template #prepend><q-icon name="search" /></template></q-input>
    <span role="status">{{ t('graphicReference.result', { count: rows.length }) }}</span>
  </div>
  <q-banner v-if="error" class="q-mb-md" role="alert">
    {{ t('graphicReference.loadError') }}
    <template #action><q-btn outline color="primary" :label="t('graphicReference.retry')" @click="loadCatalog" /></template>
  </q-banner>
  <q-table :rows="rows" :columns="columns" row-key="name" :filter="filter || ''" :loading="loading"
    :rows-per-page-options="[10, 20, 50, 100, 500]" :pagination="{ rowsPerPage: 50 }" wrap-cells flat bordered>
    <template #body-cell-preview="scope"><q-td :props="scope">
      <div class="row items-center q-gutter-md no-wrap">
        <template v-for="size in [16, 24, 32]" :key="size">
          <DocumentTagIcon v-if="family === 'emoji' || family === 'mdi' || family === 'awesome'" :icon="scope.row.name" :size="`${size}px`" />
          <q-icon v-else :name="family === 'artwork' ? `img:${scope.row.name}` : scope.row.name" :size="`${size}px`" />
        </template>
      </div>
    </q-td></template>
    <template #body-cell-sources="scope"><q-td :props="scope">
      <details v-if="scope.row.sources.length"><summary>{{ t('graphicReference.source') }} ({{ scope.row.sources.length }})</summary>
        <code v-for="file in scope.row.sources" :key="file" class="source-file">{{ file }}</code>
      </details>
    </q-td></template>
  </q-table>
  <h3 class="text-h6 q-mt-xl">{{ t('graphicReference.inventory') }}</h3>
  <p>{{ t('graphicReference.inventoryHint') }}</p>
  <q-table :rows="inventory.components" :columns="componentColumns" row-key="name" :filter="filter || ''"
    :rows-per-page-options="[10, 20, 50, 100, 500]" :pagination="{ rowsPerPage: 50 }" flat bordered wrap-cells>
    <template #body-cell-sources="scope"><q-td :props="scope"><details><summary>{{ t('graphicReference.source') }} ({{ scope.row.sources.length }})</summary>
      <code v-for="file in scope.row.sources" :key="file" class="source-file">{{ file }}</code>
    </details></q-td></template>
  </q-table>
</template>
<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableColumn } from 'quasar'
import { DocumentTagIcon, loadTagEmojiIcons } from '../../../graphicReferenceContributions'
import { artwork, inventory, type GraphicEntry } from './inventory'
const { t, mergeLocaleMessage, locale } = useI18n()
type Family = 'material' | 'artwork' | 'emoji' | 'mdi' | 'awesome'
const family = ref<Family>('material'), filter = ref(''), loading = ref(false), error = ref(false)
const catalog = shallowRef<GraphicEntry[]>([])
const families = computed(() => (['material', 'artwork', 'emoji', 'mdi', 'awesome'] as const).map(value => ({ value, label: t(`graphicReference.${value}`) })))
const rows = computed(() => family.value === 'material' ? inventory.glyphs : family.value === 'artwork'
  ? artwork.map(name => ({ name, sources: [`public${name}`] })) : catalog.value)
const columns = computed<QTableColumn[]>(() => [
  { name: 'preview', label: t('graphicReference.preview'), field: 'name', align: 'left' },
  { name: 'name', label: t('graphicReference.name'), field: 'name', align: 'left', sortable: true },
  { name: 'sources', label: t('graphicReference.source'), field: 'sources', align: 'left' },
])
const componentColumns = computed(() => columns.value.filter(column => column.name !== 'preview'))
let request = 0
async function loadCatalog(): Promise<void> {
  const current = ++request
  const selected = family.value
  error.value = false
  catalog.value = []
  loading.value = selected !== 'material' && selected !== 'artwork'
  if (selected === 'material' || selected === 'artwork') return
  try {
    const icons = await loadTagEmojiIcons((language, messages) => mergeLocaleMessage(language, messages), selected, locale.value)
    if (current === request) catalog.value = icons.map(icon => ({ name: icon.value, sources: [`app/memory/emoji/${selected === 'emoji' ? 'catalog' : selected}.ts`] }))
  } catch { if (current === request) error.value = true }
  finally { if (current === request) loading.value = false }
}
watch([family, locale], loadCatalog, { immediate: true })
</script>
<style scoped>
.family-select { min-width: min(100%, 240px); }
.source-file { display: block; overflow-wrap: anywhere; white-space: normal; }
</style>
