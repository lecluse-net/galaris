<template>
  <q-dialog :model-value="true" aria-labelledby="plugin-import-title" @update:model-value="onVisibility">
    <q-card class="galaris-dialog-card plugin-dialog">
      <DialogHeader title-id="plugin-import-title" :title="t(source === 'catalogue' ? 'plugins.catalogue' : 'plugins.importTitle')" :close-label="t('common.close')" />
      <q-card-section class="galaris-dialog-body">
        <q-file v-if="source === 'file'" v-model="file" outlined clearable accept=".zip" :disable="installing" :label="t('plugins.archive')">
          <template #prepend><q-icon name="folder_zip" /></template>
        </q-file>
        <template v-else>
          <q-select v-model="catalogueSelection" outlined :options="catalogue" :loading="awaitingCatalogue"
            :option-label="catalogueLabel" :disable="installing || awaitingCatalogue" :label="t('plugins.catalogueRelease')" />
          <p v-if="!awaitingCatalogue && !catalogue.length && !error" class="q-mt-sm">{{ t('plugins.emptyCatalogue') }}</p>
        </template>
        <q-linear-progress v-if="inspecting" indeterminate class="q-mt-md" />
        <q-banner v-if="error" role="alert" rounded class="bg-solaire-red-light text-negative q-mt-md">
          {{ error }}
          <template #action>
            <q-btn v-if="source === 'catalogue'" outline color="primary" :label="t('common.retry')" @click="retryCatalogue" />
            <q-btn v-else-if="file && !preview" outline color="primary" :label="t('common.retry')" @click="inspect(file)" />
          </template>
        </q-banner>
        <PluginManifest v-if="preview" class="q-mt-md" :preview="preview" />
        <q-checkbox v-if="preview?.can_force" v-model="force" :label="t('plugins.force')" class="q-mt-sm" />
      </q-card-section>
      <q-card-actions align="right" class="galaris-dialog-actions">
        <q-btn outline color="primary" :label="t('common.cancel')" v-close-popup />
        <q-btn color="primary" :label="t('plugins.install')" :disable="!canInstall" :loading="installing" @click="install" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogHeader } from '@/core/util'
import PluginManifest from './PluginManifest.vue'
import { pluginApi, pluginErrorCode, type PluginPreview, type PluginRelease } from '../services/pluginApi'

const { source, installRelease } = defineProps<{
  source: 'file' | 'catalogue'
  installRelease: (file: File, preview: PluginPreview, force: boolean) => Promise<PluginRelease>
}>()
const emit = defineEmits<{ close: []; installed: [PluginRelease] }>()
const { t, te, locale } = useI18n()
const file = ref<File | null>(null)
const preview = ref<PluginPreview | null>(null)
const error = ref('')
const inspecting = ref(false)
const installing = ref(false)
const force = ref(false)
const catalogue = ref<PluginPreview[]>([])
const catalogueSelection = ref<PluginPreview | null>(null)
const awaitingCatalogue = ref(false)
const canInstall = computed(() => preview.value?.compatibility === 'supported' || (preview.value?.can_force && force.value))
let generation = 0
let catalogueRequest = 0

function showError(cause: unknown) {
  const key = `plugins.messages.${pluginErrorCode(cause)}`
  error.value = t(te(key) ? key : 'plugins.messages.request_failed')
}

function onVisibility(visible: boolean) {
  if (!visible) emit('close')
}

async function inspect(selected: File | null) {
  const request = ++generation
  preview.value = null
  force.value = false
  error.value = ''
  inspecting.value = selected !== null
  if (!selected) return
  try {
    const result = await pluginApi.preview(selected)
    if (request === generation) preview.value = result
  } catch (cause) {
    if (request === generation) showError(cause)
  } finally {
    if (request === generation) inspecting.value = false
  }
}

async function install() {
  if (!file.value || !preview.value || !canInstall.value || installing.value) return
  installing.value = true
  error.value = ''
  try {
    const release = await installRelease(file.value, preview.value, force.value)
    emit('installed', release)
  } catch (cause) {
    showError(cause)
  } finally {
    installing.value = false
  }
}

function catalogueLabel(entry: PluginPreview | null): string {
  if (!entry) return ''
  const { label, version, code } = entry.manifest
  return `${locale.value === 'fr' ? label.fr : label.en} · ${version} · ${code}`
}

async function loadCatalogue() {
  const request = ++catalogueRequest
  awaitingCatalogue.value = true
  error.value = ''
  try {
    const result = await pluginApi.catalogue()
    if (catalogueRequest === request) catalogue.value = result
  } catch (cause) {
    if (catalogueRequest === request) showError(cause)
  } finally {
    if (catalogueRequest === request) awaitingCatalogue.value = false
  }
}

async function selectArchive(release: PluginPreview | null) {
  const request = ++catalogueRequest
  file.value = null
  if (!release) return
  await inspect(null)
  awaitingCatalogue.value = true
  try {
    const archive = await pluginApi.catalogueFile(release)
    if (catalogueRequest === request) file.value = archive
  } catch (cause) {
    if (catalogueRequest === request) showError(cause)
  } finally {
    if (catalogueRequest === request) awaitingCatalogue.value = false
  }
}

function retryCatalogue() {
  if (file.value) void inspect(file.value)
  else if (catalogueSelection.value) void selectArchive(catalogueSelection.value)
  else void loadCatalogue()
}

watch(file, inspect)
watch(catalogueSelection, selectArchive)
onMounted(() => { if (source === 'catalogue') void loadCatalogue() })
onBeforeUnmount(() => { generation++; catalogueRequest++ })
</script>

<style scoped>
.plugin-dialog { width: min(100%, 640px); }
</style>
