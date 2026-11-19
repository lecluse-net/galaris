<template>
  <q-page class="q-pa-md">
    <PageHeader :icon="navigationIcon('extension')" :title="t('plugins.title')" :description="t('plugins.description')" />

    <q-banner v-if="error" role="alert" rounded class="bg-solaire-red-light text-negative q-mb-md">
      {{ error }}
      <template #action><q-btn color="primary" outline :label="t('common.retry')" @click="load" /></template>
    </q-banner>
    <div v-if="canEdit || rows.length" class="row items-center justify-end q-gutter-sm q-mb-md">
      <q-input v-if="rows.length" v-model="query" clearable outlined dense :label="t('plugins.search')" class="col-12 col-sm">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <q-btn v-if="canEdit" outline color="primary" icon="storefront" :label="t('plugins.catalogue')" @click="importSource = 'catalogue'" />
      <q-btn v-if="canEdit" color="primary" icon="upload_file" :label="t('plugins.importTitle')" @click="importSource = 'file'" />
    </div>
    <q-table grid hide-header flat class="plugins-grid" :rows="rows" :columns="columns" row-key="code" :loading="loading" :filter="query ?? ''"
      v-model:pagination="pagination" :rows-per-page-options="[10, 20, 50, 100, 500]"
      :rows-per-page-label="t('plugins.pageSize')" :no-data-label="t('plugins.empty')" :no-results-label="t('plugins.noResults')">
      <template #item="props">
        <PluginCard :key="props.row.code" :entry="props.row.release" :can-edit="canEdit" :change-release="changeRelease" />
      </template>
    </q-table>

    <PluginImportDialog v-if="importSource" :source="importSource" :install-release="installRelease" @close="importSource = null" @installed="importSource = null" />
  </q-page>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { QTableColumn } from 'quasar'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { navigationIcon } from '@/core/navigation'
import { PageHeader } from '@/core/util'
import PluginImportDialog from '../components/PluginImportDialog.vue'
import PluginCard from '../components/PluginCard.vue'
import { pluginApi, type PluginAction, type PluginInventoryEntry, type PluginPreview } from '../services/pluginApi'

const { t, locale } = useI18n()
const privilegesStore = usePrivilegeStore()
const canEdit = computed(() => privilegesStore.hasPrivilege(privileges.PLUGIN_EDIT))
const inventory = ref<PluginInventoryEntry[]>([])
const loading = ref(true), error = ref(''), query = ref<string | null>('')
const importSource = ref<'file' | 'catalogue' | null>(null)
const pagination = ref({ page: 1, rowsPerPage: 50 })
const changing = new Set<string>()
let generation = 0
let mounted = true

const rows = computed(() => inventory.value.map(release => ({
  release,
  code: release.manifest.code,
  label: locale.value.startsWith('fr') ? release.manifest.label.fr : release.manifest.label.en,
})))
const columns = computed<QTableColumn<(typeof rows.value)[number]>[]>(() => [
  { name: 'label', label: t('plugins.title'), field: 'label' },
  { name: 'code', label: t('plugins.code'), field: 'code' },
])

async function load() {
  const request = ++generation
  loading.value = true
  error.value = ''
  try {
    const result = await pluginApi.list()
    if (request === generation) inventory.value = result
  } catch {
    if (request === generation) error.value = t('plugins.messages.request_failed')
  } finally {
    if (request === generation) loading.value = false
  }
}

async function installRelease(file: File, preview: PluginPreview, force: boolean) {
  const release = await pluginApi.install(file, preview, force)
  if (mounted) {
    query.value = ''
    await load()
    const index = inventory.value.findIndex(entry => entry.manifest.code === release.manifest.code)
    if (mounted && index >= 0) {
      pagination.value.page = Math.floor(index / pagination.value.rowsPerPage) + 1
    }
  }
  return release
}

async function changeRelease(release: PluginInventoryEntry, action: PluginAction) {
  const { code, version } = release.manifest
  if (!canEdit.value || changing.has(code)) return
  changing.add(code)
  try {
    const updated = await pluginApi.change(release, action)
    if (mounted) {
      inventory.value = inventory.value.map(entry => entry.manifest.code === code &&
        (entry.manifest.version === version || ('selected' in updated && updated.selected)) ? updated : entry)
      await load()
    }
    return updated
  } finally {
    changing.delete(code)
  }
}

onMounted(load)
onBeforeUnmount(() => {
  mounted = false
  generation++
})
</script>

<style scoped>
.plugins-grid :deep(.q-table__grid-content) {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 510px), 1fr));
  gap: 16px;
  width: 100%;
  margin: 0;
}
</style>
