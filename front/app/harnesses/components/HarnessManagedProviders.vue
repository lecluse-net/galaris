<template>
  <section :aria-label="t('harnesses.preferences.activationTitle')">
    <h2 class="text-subtitle1 text-weight-medium q-mt-none q-mb-xs">{{ t('harnesses.preferences.activationTitle') }}</h2>
    <p class="text-body2 q-mt-none">{{ t('harnesses.preferences.activationHint') }}</p>
    <div class="managed-providers">
      <q-card v-for="entry in entries" :key="entry.id" flat bordered class="managed-provider"
        :class="{ 'managed-provider--enabled': entry.enabled }">
        <q-card-section class="row items-center no-wrap q-gutter-sm q-pa-sm">
          <q-avatar square size="28px"><img :src="harnessBrand(entry.provider_code).logo" alt="" /></q-avatar>
          <div class="col managed-provider__name">
            <div class="text-body2 text-weight-medium">{{ entry.name }} <q-icon v-if="entry.provider_code === 'deepseek_harness'" name="science"><q-tooltip>{{ t('harnesses.catalog.experimentalHint') }}</q-tooltip></q-icon></div>
            <div class="text-caption">{{ t(entry.enabled ? 'harnesses.preferences.enabled' : 'harnesses.preferences.disabled') }} · {{ t('harnesses.preferences.assigned', { count: entry.assigned_agents }) }}</div>
          </div>
          <q-spinner v-if="busy === entry.id" color="primary" />
          <q-toggle :model-value="entry.enabled" :disable="!canEdit || busy !== null" color="positive"
            :aria-label="t('harnesses.preferences.activate', { name: entry.name })" @update:model-value="requestChange(entry, $event)" />
        </q-card-section>
        <q-card-section v-if="entry.last_error" class="q-pt-none">
          <div role="alert">{{ entry.last_error }}</div>
        </q-card-section>
      </q-card>
    </div>
    <q-banner v-if="!entries.length" rounded>{{ t('harnessSettings.noProviders') }}</q-banner>
    <q-banner v-if="error" rounded class="q-mt-md" role="alert">{{ error }}</q-banner>

    <div class="row items-center justify-between q-mt-sm q-gutter-sm">
      <span class="text-caption">{{ t('harnesses.preferences.modelsShort') }}</span>
      <q-btn flat dense no-caps color="primary" icon="psychology" :label="t('harnesses.catalog.configureLlmProfiles')" :to="{ path: '/llm', query: { tab: 'usage' } }" />
    </div>

    <section v-for="entry in enabledEntries" :key="entry.id" class="managed-providers__settings q-mt-lg"
      :aria-label="t('harnesses.preferences.providerSettings', { name: entry.name })">
      <h2 class="text-h6 q-mt-none">{{ t('harnesses.preferences.providerSettings', { name: entry.name }) }}</h2>
      <HarnessProviderSettings :provider="entry.provider_code" />
      <HarnessExecutionSettings v-if="canEdit" :provider-code="entry.provider_code" class="q-mt-lg" />
    </section>

    <q-dialog :model-value="pending !== null" @update:model-value="!$event && (pending = null)">
      <q-card class="managed-providers__confirm">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ t('harnesses.catalog.disableTitle') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section>{{ t('harnesses.catalog.disableConfirm', { name: pending?.name ?? '', count: pending?.assigned_agents ?? 0 }) }}</q-card-section>
        <q-card-actions align="right" class="galaris-dialog-actions">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn color="warning" :label="t('harnesses.catalog.disable')" :loading="busy !== null" :disable="!canEdit" @click="confirmDisable" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { HarnessProviderSettings } from '@/core/params'
import { harnessBrand } from '../branding'
import HarnessExecutionSettings from './HarnessExecutionSettings.vue'
import { harnessService, type HarnessCatalogEntry } from '../services/harnessService'

const props = defineProps<{ entries: HarnessCatalogEntry[] }>()
const emit = defineEmits<{ updated: [entry: HarnessCatalogEntry] }>()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.PARAMS_EDIT))
const enabledEntries = computed(() => props.entries.filter(entry => entry.enabled))
const busy = ref<string | null>(null)
const pending = ref<HarnessCatalogEntry | null>(null)
const error = ref('')
let disposed = false

function requestChange(entry: HarnessCatalogEntry, enabled: boolean): void {
  if (!canEdit.value || busy.value !== null) return
  error.value = ''
  if (enabled) void persist(entry, true)
  else pending.value = entry
}
async function confirmDisable(): Promise<void> {
  if (pending.value) await persist(pending.value, false)
}
async function persist(entry: HarnessCatalogEntry, enabled: boolean): Promise<void> {
  if (!canEdit.value || busy.value !== null) return
  busy.value = entry.id
  error.value = ''
  try {
    const result = await harnessService.updateCatalogEntry(entry.id, {
      name: entry.name, enabled, base_url: entry.base_url, model: entry.model, settings: entry.settings,
    })
    if (disposed) return
    emit('updated', result.data)
    pending.value = null
  } catch {
    if (!disposed) { error.value = t('harnesses.catalog.activationError'); pending.value = null }
  } finally { if (!disposed) busy.value = null }
}
onBeforeUnmount(() => { disposed = true })
</script>

<style scoped>
.managed-providers { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.managed-provider { border-radius: 8px; min-width: 0; }
.managed-provider--enabled { border-color: var(--solaire-green-accent); }
.managed-provider__name { min-width: 0; overflow-wrap: anywhere; }
.managed-providers__settings { border: 1px solid var(--solaire-gray-accent); border-radius: 8px; padding: 16px; }
.managed-providers__confirm { width: 560px; max-width: 92vw; }
@media (max-width: 1023px) { .managed-providers { grid-template-columns: minmax(0, 1fr); } }
</style>
