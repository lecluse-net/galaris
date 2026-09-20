<template>
  <section class="q-pa-md" :aria-label="t('harnesses.release.title')">
    <q-spinner v-if="loading" />
    <q-banner v-else-if="error" role="alert">
      {{ t('harnesses.release.downloadError') }}
      <template #action><q-btn flat :label="t('common.retry')" @click="load" /></template>
    </q-banner>
    <template v-else-if="release">
      <div class="row items-center justify-between q-gutter-sm">
        <span class="text-caption">{{ t('harnesses.release.versions', { installed: diagnostics?.manager_version || t('harnesses.release.unknown'), available: release.version }) }}</span>
        <q-btn flat dense no-caps icon="system_update" :label="t('harnesses.preferences.updateManager')" @click="updateOpen = true" />
      </div>
      <q-banner v-if="diagnostics && ['update_available', 'newer', 'unknown'].includes(diagnostics.version_status)"
        dense class="manager-release__notice q-mt-sm" role="status">
        <template #avatar><q-icon name="system_update" /></template>
        {{ t(`harnesses.release.states.${diagnostics.version_status}`) }}
      </q-banner>
      <q-dialog v-model="updateOpen">
        <q-card class="manager-release__dialog">
          <q-card-section class="galaris-dialog-title row items-center no-wrap">
            <div class="text-h6">{{ t('harnesses.preferences.updateManager') }}</div>
            <q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
          </q-card-section>
          <q-card-section>
      <p>{{ t('harnesses.release.updateHint') }}</p>
      <pre class="manager-release__command">make update</pre>
      <p class="text-caption">{{ t('harnesses.release.firstUpdate') }}</p>
      <p class="text-caption">{{ t('harnesses.release.endpoint') }} <code>{{ release.update_url }}</code></p>
      <q-btn outline icon="download" :label="t('harnesses.release.sourceZip', { version: release.version })" :loading="downloading" @click="download" />
      <p class="text-caption q-mt-sm q-mb-none">{{ t('harnesses.release.sourceHint') }}</p>
          </q-card-section>
          <q-card-actions align="right"><q-btn v-close-popup flat :label="t('common.close')" /></q-card-actions>
        </q-card>
      </q-dialog>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { exportFile } from 'quasar'
import { useI18n } from 'vue-i18n'
import { managerService, type ManagerDiagnostics, type ManagerRelease } from '../services/managerService'

defineProps<{ diagnostics: ManagerDiagnostics | null }>()
const { t } = useI18n()
const release = ref<ManagerRelease | null>(null)
const loading = ref(false)
const downloading = ref(false)
const error = ref(false)
const updateOpen = ref(false)
let disposed = false
async function load(): Promise<void> {
  if (loading.value) return
  loading.value = true
  error.value = false
  try { const result = await managerService.release(); if (!disposed) release.value = result }
  catch { if (!disposed) error.value = true }
  finally { if (!disposed) loading.value = false }
}
async function download(): Promise<void> {
  if (downloading.value || !release.value) return
  downloading.value = true
  try {
    const archive = await managerService.archive()
    if (!disposed && exportFile('harness-manager-source.zip', archive, 'application/zip') !== true) error.value = true
  } catch { if (!disposed) error.value = true }
  finally { if (!disposed) downloading.value = false }
}
onMounted(load)
onBeforeUnmount(() => { disposed = true })
</script>

<style scoped>
.manager-release__notice { background: var(--solaire-orange-light); }
.body--dark .manager-release__notice { background: var(--solaire-orange-dark); }
.manager-release__command { white-space: pre-wrap; }
.manager-release__dialog { width: 680px; max-width: 94vw; }
code { overflow-wrap: anywhere; }
</style>
