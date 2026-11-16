<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card class="galaris-dialog-card" style="width: min(820px, 95vw); max-width: 95vw; max-height: 90vh; overflow-y: auto">
      <DialogHeader :title="$t('services.globalParamsFor', { name: tool ? localizedToolLabel(tool) : '' })" :close-label="$t('common.close')" />

      <q-card-section class="galaris-dialog-body">
        <q-linear-progress v-if="loading" indeterminate color="primary" class="q-mb-md" />
        <q-banner v-if="loadError" role="alert" class="q-mb-md">{{ loadError }}
          <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="load" /></template>
        </q-banner>
        <q-banner v-if="usersError" role="alert" class="q-mb-md">{{ usersError }}
          <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="loadUsers" /></template>
        </q-banner>
        <q-banner dense rounded class="bg-solaire-blue-light text-solaire-blue q-mb-md">
          <template #avatar><q-icon name="info" /></template>
          {{ $t('services.globalParamsHint') }}
        </q-banner>
        <div v-if="!loading && !loadError" class="q-gutter-y-md">
          <div v-for="row in globalParamRows" :key="row.name" class="tool-section">
            <div class="row items-start q-col-gutter-md">
              <div class="col">
                <div class="text-weight-medium">{{ localizedParamLabel(row, tool?.code) }}</div>
                <code v-if="localizedParamLabel(row, tool?.code) !== row.name" class="text-caption">{{ row.name }}</code>
                <div v-if="row.description" class="text-caption text-grey-7 q-mb-sm">
                  {{ localizedGlobalParamDescription(row) }}
                </div>
                <ConnectionParamInput
                  v-model="row.value"
                  :name="row.name"
                  :definition="row"
                  :tool-code="tool?.code"
                  :user-options="userOptions"
                  :loading-users="usersLoading"
                  :placeholder="row.secret && row.configured && !row.clear ? $t('services.secretConfigured') : row.default"
                  @update:model-value="row.clear = false"
                >
                  <template v-if="row.configured || row.value" #append>
                    <q-btn
                      flat round dense icon="close" size="sm"
                      :aria-label="$t('services.clearGlobalParam')"
                      @click="clearGlobalParam(row)"
                    />
                  </template>
                </ConnectionParamInput>
              </div>
              <q-toggle
                v-model="row.forced"
                :disable="row.clear || (!row.configured && !row.value && !row.default)"
                :label="$t('services.forceGlobalParam')"
                color="negative"
                class="col-auto q-mt-lg"
                @update:model-value="setGlobalParamForced(row, $event)"
              />
            </div>
          </div>
        </div>
      </q-card-section>

      <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
        <q-btn outline color="primary"  :label="$t('common.cancel')" v-close-popup />
        <q-btn color="primary" :label="$t('common.save')" :aria-label="$t('common.save')" :loading="savingGlobalParams" :disable="savingGlobalParams || loading || Boolean(loadError) || !canEdit" @click="saveGlobalParams" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail, sessionGeneration } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { DialogHeader } from '@/core/util/facade'
import serviceApi, { type Service, type ConnectionParamDef, type ConnectionParamOption, type ServiceGlobalParamUpdate } from '../services/serviceApi'
import { connectionParamLabel, connectionParamMessageKey, sortedConnectionParamEntries, toolMessageKey } from '../presentation'
import { loadServiceUserOptions } from '../parameterChoices'
import ConnectionParamInput from './ConnectionParamInput.vue'

const props = defineProps<{ modelValue: boolean; tool: Service | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: [] }>()
const { t, te } = useI18n(), $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.SERVICE_EDIT))
type GlobalParamRow = ConnectionParamDef & {
  name: string
  type: string
  description: string
  default: string
  secret: boolean
  configured: boolean
  forced: boolean
  clear: boolean
  value: string | null
}

const globalParamRows = ref<GlobalParamRow[]>([]), userOptions = ref<ConnectionParamOption[]>([])
const loading = ref(false), usersLoading = ref(false)
const pendingSaves = reactive(new Set<number>())
const savingGlobalParams = computed(() => props.tool !== null && pendingSaves.has(props.tool.id))
const loadError = ref(''), usersError = ref('')
let opening = 0
function context() {
  const generation = opening, session = sessionGeneration(), id = props.tool?.id
  return { id, current: () => generation === opening && props.modelValue && session === sessionGeneration() }
}
function localizedToolLabel(tool: Service): string {
  const key = toolMessageKey(tool.code, 'label')
  return key && (!tool.can_edit || tool.label === t(key, {}, { locale: 'en' })) ? t(key) : tool.label
}
function localizedParamLabel(param: { name: string } & Partial<ConnectionParamDef>, toolCode?: string): string {
  return connectionParamLabel(toolCode, param.name, param, t, te)
}
function localizedGlobalParamDescription(row: GlobalParamRow): string {
  const key = props.tool ? connectionParamMessageKey(props.tool.code, row.name, row) : null
  return key ? t(key) : row.description
}
async function loadUsers(): Promise<void> {
  const request = context()
  usersLoading.value = true; usersError.value = ''
  try {
    const choices = await loadServiceUserOptions()
    if (request.current()) userOptions.value = choices
  } catch (error) {
    if (request.current()) usersError.value = apiErrorDetail(error) ?? t('common.viewLoadError')
  } finally { if (request.current()) usersLoading.value = false }
}
async function load(): Promise<void> {
  const request = context(), tool = props.tool
  if (!tool || request.id === undefined) return
  loading.value = true; loadError.value = ''
  try {
    const { data } = await serviceApi.getGlobalParams(request.id)
    if (!request.current()) return
    globalParamRows.value = sortedConnectionParamEntries(tool.connection_schema.params)
      .filter(([name]) => name !== 'services.management_scope')
      .map(([name, definition]) => globalParamRow(name, definition, data.params[name]))
    if (globalParamRows.value.some(row => row.type === 'user')) await loadUsers()
  } catch (error) {
    if (request.current()) loadError.value = apiErrorDetail(error) ?? t('common.viewLoadError')
  } finally { if (request.current()) loading.value = false }
}
function globalParamRow(name: string, definition: ConnectionParamDef, current?: Service['global_params'][string]): GlobalParamRow {
  return { ...definition, name, description: definition.description ?? '', default: definition.type === 'password' ? '' : definition.default || '',
    secret: definition.type === 'password', configured: current?.configured ?? false, forced: current?.forced ?? false, clear: false,
    value: definition.type === 'password' ? '' : current ? current.value ?? '' : definition.default || '' }
}

function clearGlobalParam(row: GlobalParamRow): void {
  row.value = ''
  row.configured = false
  row.forced = false
  row.clear = true
}

function setGlobalParamForced(row: GlobalParamRow, forced: boolean): void {
  if (forced && !row.configured && !row.value && row.default) {
    row.value = row.default
    row.clear = false
  }
}


async function saveGlobalParams(): Promise<void> {
  const request = context()
  if (request.id === undefined || !canEdit.value || loading.value || loadError.value || savingGlobalParams.value) return
  const params: Record<string, ServiceGlobalParamUpdate> = {}
  for (const row of globalParamRows.value) {
    const value = row.value === '' ? null : row.value
    params[row.name] = { value, forced: row.forced, clear: row.clear || (!row.secret && value === null) }
  }
  pendingSaves.add(request.id)
  try {
    await serviceApi.updateGlobalParams(request.id, params)
    emit('saved')
    if (!request.current()) return
    emit('update:modelValue', false)
    $q.notify({ type: 'positive', message: t('services.globalParamsUpdated') })
  } catch (error) {
    if (request.current()) $q.notify({ type: 'negative', message: apiErrorDetail(error) ?? t('services.globalParamsError') })
  } finally { pendingSaves.delete(request.id) }
}
watch(() => [props.modelValue, props.tool?.id] as const, ([open]) => {
  opening++; loading.value = false; usersLoading.value = false
  globalParamRows.value = []; userOptions.value = []; loadError.value = ''; usersError.value = ''
  if (open) void load()
}, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { opening++ })
</script>
<style scoped>


.tool-section {
  border: 1px solid rgba(0, 0, 0, .24);
  border-radius: 4px;
}

.tool-section {
  padding: 16px;
  background: #ffffff;
}

:global(body.body--dark) .tool-section {
  background: #1d1d1d;
}

:global(body.body--dark) .tool-section {
  border-color: rgba(255, 255, 255, .6);
}

@media (max-width: 1023px) {

  .tool-section {
    padding: 12px;
  }
}
</style>
