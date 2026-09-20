<template>
  <section :aria-label="t('harnesses.preferences.external')" class="external-harnesses">
    <div class="external-harnesses__toolbar q-mb-lg">
      <div class="col">
        <h2 class="text-subtitle1 text-weight-medium q-mt-none q-mb-xs">{{ t('harnesses.preferences.external') }}</h2>
        <p class="text-body2 q-ma-none">{{ t('harnesses.preferences.externalHint') }}</p>
      </div>
      <q-btn v-if="canEdit" color="primary" icon="add" :label="t('harnesses.catalog.addApi')" @click="openEditor(null)" />
    </div>
    <q-input v-if="entries.length > 5" v-model="search" outlined clearable :label="t('harnesses.preferences.search')" class="q-mb-md">
      <template #prepend><q-icon name="search" /></template>
    </q-input>
    <q-list v-if="filtered.length" bordered separator class="external-harnesses__list">
      <q-item v-for="entry in filtered" :key="entry.id" class="external-harnesses__row">
        <q-item-section avatar><q-icon :name="harnessBrand(entry.provider_code).icon" size="32px" /></q-item-section>
        <q-item-section class="external-harnesses__details">
          <q-item-label class="text-weight-medium">{{ entry.name }}</q-item-label>
          <q-item-label caption class="external-harnesses__address">{{ entry.base_url }}</q-item-label>
          <q-item-label caption>{{ entry.model }} · {{ t('harnesses.preferences.assigned', { count: entry.assigned_agents }) }}</q-item-label>
          <q-item-label v-if="entry.last_error" caption role="alert">{{ entry.last_error }}</q-item-label>
        </q-item-section>
        <q-item-section side class="external-harnesses__actions">
          <span class="text-caption">{{ t(entry.enabled ? 'harnesses.preferences.enabled' : 'harnesses.preferences.disabled') }}</span>
          <q-btn flat color="primary" :icon="canEdit ? 'edit' : 'visibility'"
            :label="t(canEdit ? 'common.edit' : 'harnesses.preferences.view')"
            @click="openEditor(entry)" />
        </q-item-section>
      </q-item>
    </q-list>
    <q-banner v-else rounded class="external-harnesses__empty">
      <template #avatar><q-icon name="cloud_queue" /></template>
      {{ t(entries.length ? 'harnesses.preferences.noResults' : 'harnesses.preferences.empty') }}
    </q-banner>
    <q-dialog v-model="editing">
      <q-card class="external-harnesses__dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ selected?.name ?? t('harnesses.catalog.addApi') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <HarnessEditor v-if="editing" :key="editorSession" :harness-id="selected?.id ?? 'new'" embedded
          @close="editing = false" @done="editing = false" @mutation="trackMutation" />
        <q-card-section v-if="editing && selected && canEdit">
          <HarnessExecutionSettings :key="editorSession" :provider-code="selected.provider_code" />
        </q-card-section>
      </q-card>
    </q-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { harnessBrand } from '../branding'
import type { HarnessCatalogEntry } from '../services/harnessService'
import HarnessEditor from './HarnessEditor.vue'
import HarnessExecutionSettings from './HarnessExecutionSettings.vue'

const props = defineProps<{ entries: HarnessCatalogEntry[] }>()
const emit = defineEmits<{ updated: [entry: HarnessCatalogEntry]; removed: [id: string] }>()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.PARAMS_EDIT))
const search = ref<string | null>('')
const editing = ref(false)
const selected = ref<HarnessCatalogEntry | null>(null)
const editorSession = ref(0)
function openEditor(entry: HarnessCatalogEntry | null): void {
  if (!entry && !canEdit.value) return
  selected.value = entry
  editorSession.value++
  editing.value = true
}
async function trackMutation(completion: Promise<HarnessCatalogEntry | string>): Promise<void> {
  try {
    const result = await completion
    if (typeof result === 'string') emit('removed', result)
    else emit('updated', result)
  } catch { /* The editor presents the error and retains its draft. */ }
}
const filtered = computed(() => {
  const query = search.value?.trim().toLocaleLowerCase() ?? ''
  return props.entries.filter(entry => `${entry.name} ${entry.base_url ?? ''} ${entry.model ?? ''}`.toLocaleLowerCase().includes(query))
})
</script>

<style scoped>
.external-harnesses { min-width: 0; }
.external-harnesses__dialog { width: 760px; max-width: 96vw; }
.external-harnesses__toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; }
.external-harnesses__toolbar > .col { flex: 1 1 260px; }
.external-harnesses__list { border-radius: 12px; }
.external-harnesses__row { padding: 16px; }
.external-harnesses__details { min-width: 0; overflow-wrap: anywhere; }
.external-harnesses__address { word-break: break-all; }
.external-harnesses__empty { background: var(--solaire-gray-light); }
.body--dark .external-harnesses__empty { background: var(--solaire-gray-dark); }
@media (max-width: 1023px) {
  .external-harnesses__row { flex-wrap: wrap; }
  .external-harnesses__actions { flex: 1 0 100%; flex-direction: row; justify-content: space-between; align-items: center; padding: 12px 0 0; }
}
</style>
