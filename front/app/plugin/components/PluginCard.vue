<template>
  <q-card tag="article" flat bordered class="plugin-card" :class="{ 'plugin-card-inactive': state === 'inactive' }"
    :aria-label="label(release.manifest.label)">
    <div class="plugin-card-identity">
      <div class="plugin-card-icon" :class="`bg-solaire-${appearance.tone}-light`">
        <q-icon :name="appearance.icon" :class="`text-solaire-${appearance.tone}`" aria-hidden="true" />
      </div>
      <q-card-section class="plugin-card-heading">
        <h2 class="text-h6 text-weight-bold q-ma-none">{{ label(release.manifest.label) }}</h2>
        <div class="text-caption">{{ release.manifest.code }} · {{ release.manifest.version }}</div>
        <div class="plugin-card-status row items-center justify-between">
          <StatusBadge :tone="statusTone" :label="t(`plugins.states.${state}`)" />
          <q-toggle v-if="sample || archiveRelease?.installed" :model-value="archiveRelease?.selected ?? release.active" size="sm" color="primary"
            :label="t('plugins.activation')" :aria-label="t('plugins.activationFor', { name: label(release.manifest.label) })"
            :aria-busy="busy" :disable="!canEdit || busy || (archiveRelease && !archiveRelease.selected && !canActivateRelease(archiveRelease))"
            @update:model-value="value => change(value ? 'activate' : 'deactivate')" />
        </div>
        <p class="text-body2 q-mt-sm q-mb-none">{{ label(release.manifest.description) }}</p>
      </q-card-section>
    </div>
    <q-separator />
    <q-card-section class="col">
      <PluginManifest :preview="release" hide-identity :download-templates="archiveRelease?.active"
        :busy="busy" @download="downloadTemplate" />
    </q-card-section>
    <q-separator v-if="archiveRelease" />
    <q-expansion-item v-if="archiveRelease" v-model="historyOpen" icon="history" :label="t('plugins.history')" @before-show="loadDetails">
      <q-card-section class="q-pt-none">
        <q-linear-progress v-if="loadingDetails" indeterminate :aria-label="t('plugins.history')" />
        <q-banner v-if="detailsError" role="alert" rounded class="bg-solaire-red-light text-negative">
          {{ detailsError }}
          <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="loadDetails" /></template>
        </q-banner>
        <template v-else-if="detail">
          <q-select v-if="detail.releases.length > 1" :model-value="release.manifest.version" outlined emit-value map-options dense
            :label="t('plugins.version')" :options="versions" :disable="busy || loadingDetails"
            @update:model-value="version = $event" />
          <q-list v-if="detail.events.length" separator class="q-mt-xs">
            <q-item v-for="(event, index) in detail.events" :key="index" class="q-px-none">
              <q-item-section>
                <q-item-label>{{ t(`plugins.events.${event.operation}`, { version: event.version }) }}</q-item-label>
                <q-item-label caption>
                  {{ d(new Date(event.occurred_at), 'short') }}
                  <span v-if="event.forced"> · {{ t('plugins.forced') }}</span>
                </q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </template>
      </q-card-section>
    </q-expansion-item>
    <q-banner v-if="actionError" role="alert" rounded class="bg-solaire-red-light text-negative q-mx-md q-mt-sm">
      {{ actionError }}
    </q-banner>
    <q-checkbox v-if="confirmRemove" v-model="removeConfirmed" class="q-mx-md q-mt-sm" :label="t('plugins.confirmRemove')" />
    <q-card-actions v-if="canRemove || canRetryActivation" align="right" class="q-pa-sm plugin-card-actions">
      <q-btn v-if="canRemove" color="negative" :disable="busy || (confirmRemove && !removeConfirmed)"
        :label="t('plugins.remove')" @click="requestRemove" />
      <q-btn v-if="canRetryActivation" color="primary" outline :disable="busy"
        :label="t('plugins.retryActivation')" @click="change('activate')" />
    </q-card-actions>
  </q-card>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { StatusBadge } from '@/core/util'
import { saveBlobAsResource } from '@/core/util/facade'
import PluginManifest from './PluginManifest.vue'
import { pluginApi, pluginErrorCode, type PluginAction, type PluginDetail, type PluginInventoryEntry } from '../services/pluginApi'
import { canActivateRelease, isDevelopmentSample, pluginAppearance, releaseState } from '../presentation'

const { entry, canEdit, changeRelease } = defineProps<{
  entry: PluginInventoryEntry
  canEdit: boolean
  changeRelease: (release: PluginInventoryEntry, action: PluginAction) => Promise<PluginInventoryEntry | undefined>
}>()
const { t, te, d, locale } = useI18n()
const detail = ref<PluginDetail | null>(null)
const historyOpen = ref(false)
const version = ref<string>()
const loadingDetails = ref(false)
const busy = ref(false)
const detailsError = ref('')
const actionError = ref('')
const confirmRemove = ref(false)
const removeConfirmed = ref(false)
const release = computed(() => version.value && version.value !== entry.manifest.version
  ? detail.value?.releases.find(item => item.manifest.version === version.value) ?? entry
  : entry)
const state = computed(() => releaseState(release.value))
const statusTone = computed(() => state.value === 'blocked' ? 'warning' : release.value.active ? 'active' : 'neutral')
const appearance = computed(() => pluginAppearance(release.value))
const sample = computed(() => isDevelopmentSample(release.value))
const archiveRelease = computed(() => isDevelopmentSample(release.value) ? undefined : release.value)
const canRemove = computed(() => canEdit && archiveRelease.value?.installed && !archiveRelease.value.selected)
const canRetryActivation = computed(() => canEdit && archiveRelease.value && state.value === 'blocked' && canActivateRelease(archiveRelease.value))
const versions = computed(() => detail.value?.releases.map(item => ({
  value: item.manifest.version,
  label: t('plugins.versionOption', { version: item.manifest.version, state: t(`plugins.states.${releaseState(item)}`) }),
})) ?? [])
let open = true
let detailRequest = 0

function label(value: { fr: string; en: string }) {
  return locale.value.startsWith('fr') ? value.fr : value.en
}

function errorMessage(cause: unknown) {
  const key = `plugins.messages.${pluginErrorCode(cause)}`
  return t(te(key) ? key : 'plugins.messages.request_failed')
}

async function loadDetails() {
  const request = ++detailRequest
  loadingDetails.value = true
  detailsError.value = ''
  try {
    const result = await pluginApi.get(entry.manifest.code)
    if (request === detailRequest) detail.value = result
  } catch (cause) {
    if (request === detailRequest) detailsError.value = errorMessage(cause)
  } finally {
    if (request === detailRequest) loadingDetails.value = false
  }
}

async function change(action: PluginAction) {
  if (busy.value) return
  busy.value = true
  actionError.value = ''
  try {
    const updated = await changeRelease(release.value, action)
    if (open && updated) {
      confirmRemove.value = false
      removeConfirmed.value = false
      if (detail.value) {
        detail.value.releases = detail.value.releases.map(item => item.manifest.version === updated.manifest.version ? updated : item)
      }
      if (historyOpen.value || detail.value) await loadDetails()
    }
  } catch (cause) {
    if (open) actionError.value = errorMessage(cause)
  } finally {
    busy.value = false
  }
}

async function downloadTemplate(code: string) {
  if (!archiveRelease.value?.active || busy.value) return
  busy.value = true
  actionError.value = ''
  try {
    const bytes = await pluginApi.dataTemplate(archiveRelease.value.manifest.code, code)
    if (open) saveBlobAsResource(bytes, `${code}.json`)
  } catch (cause) {
    if (open) actionError.value = errorMessage(cause)
  } finally {
    busy.value = false
  }
}

function requestRemove() {
  if (confirmRemove.value && removeConfirmed.value) void change('remove')
  else confirmRemove.value = true
}

watch(version, () => {
  confirmRemove.value = false
  removeConfirmed.value = false
  actionError.value = ''
})
onBeforeUnmount(() => {
  open = false
  detailRequest++
})
</script>

<style scoped>
.plugin-card { display: flex; flex-direction: column; min-width: 0; height: 100%; }
.plugin-card-identity { display: grid; grid-template-columns: 100px minmax(0, 1fr); }
.plugin-card-icon { display: grid; place-items: center; font-size: 48px; }
.plugin-card-heading { overflow-wrap: anywhere; }
.plugin-card-heading h2 { line-height: 1.35; }
.plugin-card-status { gap: 4px 8px; }
.plugin-card-inactive .plugin-card-heading { background: var(--solaire-gray-light); }
.body--dark .plugin-card-inactive .plugin-card-heading { background: var(--solaire-gray-dark); }
.plugin-card-inactive .plugin-card-icon .q-icon { opacity: .65; }
.plugin-card-actions { gap: 4px; }
@media (max-width: 599px) {
  .plugin-card-identity { grid-template-columns: 68px minmax(0, 1fr); }
  .plugin-card-icon { font-size: 36px; }
}
</style>
