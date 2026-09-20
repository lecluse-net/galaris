<template>
  <section class="harness-preferences" :aria-label="t('harnessSettings.title')">
    <q-tabs :model-value="tab" align="left" active-color="primary" indicator-color="primary" class="text-primary"
      @update:model-value="selectTab">
      <q-tab v-if="canEdit" name="internal" icon="smart_toy" :label="t('harnesses.preferences.internal')" />
      <q-tab name="managed" icon="dns" :label="t('harnesses.preferences.managed')" />
      <q-tab name="external" icon="cloud" :label="t('harnesses.preferences.external')" />
    </q-tabs>
    <q-separator />
    <div v-if="catalogTab && loading" class="row justify-center q-pa-xl" role="status" :aria-label="t('common.loading')">
      <q-spinner color="primary" size="36px" />
    </div>
    <q-banner v-else-if="catalogTab && failed" class="q-my-lg" role="alert">
      {{ t('harnesses.catalog.loadError') }}
      <template #action><q-btn flat :label="t('common.retry')" @click="load" /></template>
    </q-banner>
    <q-tab-panels v-show="!catalogTab || (!loading && !failed)" :model-value="tab" keep-alive animated>
      <q-tab-panel v-if="canEdit" name="internal" :aria-label="t('harnesses.preferences.internal')">
        <p>{{ t('harnesses.preferences.internalHint') }}</p>
        <h2 class="text-h6 q-mt-none">{{ t('harnesses.inputFiles.title') }}</h2>
        <SettingsFields :fields="inputFields" class="q-mb-lg" />
        <HarnessExecutionSettings provider-code="internal" />
      </q-tab-panel>
      <q-tab-panel name="managed">
        <HarnessManagerHelp />
        <HarnessManagedProviders :entries="managed" @updated="updateEntry" />
        <q-expansion-item class="harness-preferences__advanced q-mt-lg" icon="code"
          :label="t('harnesses.catalog.composeTitle')" :caption="t('harnesses.preferences.composeHint')">
          <div class="q-pa-md">
            <p class="text-body2">{{ t('harnesses.catalog.composeHint') }}</p>
            <SettingsFields :fields="managedComposeFields" />
          </div>
        </q-expansion-item>
      </q-tab-panel>
      <q-tab-panel name="external">
        <HarnessCatalogGrid :entries="external" @updated="updateEntry" @removed="removeEntry" />
      </q-tab-panel>
    </q-tab-panels>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { SettingsFields } from '@/core/params'
import { harnessService, type HarnessCatalogEntry } from '../services/harnessService'
import { managedComposeFields } from '../managedSettings'
import { inputFields } from '../runtimeSettings'
import HarnessCatalogGrid from './HarnessCatalogGrid.vue'
import HarnessExecutionSettings from './HarnessExecutionSettings.vue'
import HarnessManagedProviders from './HarnessManagedProviders.vue'
import HarnessManagerHelp from './HarnessManagerHelp.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.PARAMS_EDIT))
const tab = computed(() => {
  const requested = route.query.tab
  if (requested === 'managed' || requested === 'external') return requested
  if (!canEdit.value) return 'managed'
  return 'internal'
})
watch(() => route.query.tab, requested => {
  if (route.path === '/params/harnesses' && (requested === 'common' || requested === 'advanced')) {
    const { tab: _tab, ...query } = route.query
    void router.replace({ path: '/params/tasks', query })
  }
}, { immediate: true })
const catalogTab = computed(() => tab.value === 'managed' || tab.value === 'external')
const entries = ref<HarnessCatalogEntry[]>([])
const managed = computed(() => entries.value.filter(item => item.containerized))
const external = computed(() => entries.value.filter(item => !item.containerized))
const loading = ref(false)
const failed = ref(false)
let disposed = false

function selectTab(value: string): void {
  void router.replace({ query: { ...route.query, tab: value } })
}
function updateEntry(entry: HarnessCatalogEntry): void {
  const exists = entries.value.some(item => item.id === entry.id)
  entries.value = exists ? entries.value.map(item => item.id === entry.id ? entry : item) : [...entries.value, entry]
}
function removeEntry(id: string): void {
  entries.value = entries.value.filter(item => item.id !== id)
}
async function load(): Promise<void> {
  if (loading.value) return
  loading.value = true
  failed.value = false
  try {
    const result = await harnessService.catalog()
    if (!disposed) entries.value = result.data
  } catch { if (!disposed) failed.value = true }
  finally { if (!disposed) loading.value = false }
}
onMounted(load)
onBeforeUnmount(() => { disposed = true })
</script>

<style scoped>
.harness-preferences { min-width: 0; }
.harness-preferences__advanced { border: 1px solid var(--solaire-gray-accent); border-radius: 12px; overflow: hidden; }
</style>
