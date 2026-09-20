<template>
  <div class="harness-detail">
    <PageHeader v-if="!embedded" :icon="providerIcon"
      :title="isNew ? t('harnesses.catalog.addApi') : form.name"
      :description="t('harnesses.catalog.detailHint')"
    />

    <q-card flat :bordered="!embedded" class="harness-detail__card">
      <div v-if="loading" class="row justify-center q-pa-xl">
        <q-spinner color="primary" size="42px" />
      </div>

      <q-banner v-else-if="loadFailed" role="alert">
        {{ t('harnesses.catalog.loadError') }}
        <template #action><q-btn flat :label="t('common.retry')" @click="load" /></template>
      </q-banner>
      <q-form v-else class="q-pa-lg q-gutter-lg" @submit.prevent="save">
        <q-banner v-if="entry?.provider_code === 'deepseek_harness'" rounded class="bg-orange-1 text-dark">
          <template #avatar><q-icon name="science" color="warning" /></template>
          <div class="text-subtitle1 text-weight-bold">{{ t('harnesses.catalog.experimental') }}</div>
          <div>{{ t('harnesses.catalog.experimentalHint') }}</div>
        </q-banner>
        <div class="row items-center q-gutter-sm">
          <q-icon :name="providerIcon" color="primary" size="32px" />
          <div class="text-h6">{{ providerLabel }}</div>
          <q-badge v-if="isOpenAi" rounded color="primary" label="API" />
        </div>

        <q-input
          v-model="form.name"
          filled
          :label="t('harnesses.catalog.name')"
          :readonly="!canEdit || !isOpenAi || busy"
          :rules="[requiredRule]"
        />

        <div>
          <q-toggle
            :model-value="form.enabled"
            color="positive"
            :disable="!canEdit || busy"
            :label="t('harnesses.catalog.enabled')"
            @update:model-value="requestEnabledChange"
          />
          <div class="text-caption text-grey-7 q-mt-sm">
            {{ t('harnesses.catalog.enabledHint') }}
          </div>
        </div>

        <q-banner v-if="usesGalarisModels" rounded class="bg-blue-1 text-primary">
          <div class="text-subtitle2 text-weight-medium">
            {{ t('harnesses.catalog.galarisRoutingTitle', { provider: providerLabel }) }}
          </div>
          <div class="text-body2 text-grey-8 q-mt-xs">
            {{ t('harnesses.catalog.galarisRoutingHint') }}
          </div>
          <q-list dense class="q-mt-sm">
            <q-item>
              <q-item-section avatar><q-icon name="speed" /></q-item-section>
              <q-item-section>
                <q-item-label>{{ t('harnesses.catalog.galarisStandard') }}</q-item-label>
                <q-item-label caption>{{ t('harnesses.catalog.galarisStandardModel') }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-item>
              <q-item-section avatar><q-icon name="rocket_launch" /></q-item-section>
              <q-item-section>
                <q-item-label>{{ t('harnesses.catalog.galarisHigh') }}</q-item-label>
                <q-item-label caption>{{ t('harnesses.catalog.galarisHighModel') }}</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
          <template #action>
            <q-btn
              flat
              color="primary"
              icon="smart_toy"
              :label="t('harnesses.catalog.configureLlmProfiles')"
              :to="{ path: '/llm', query: { tab: 'usage' } }"
            />
          </template>
        </q-banner>

        <template v-if="isOpenAi">
          <div>
            <q-toggle :model-value="form.settings.streams_ai_messages !== false" :disable="!canEdit || busy"
              :label="t('harnesses.catalog.streamsAiMessages')"
              @update:model-value="form.settings.streams_ai_messages = $event" />
            <div class="text-caption">{{ t('harnesses.catalog.streamsAiMessagesHint') }}</div>
          </div>
          <q-separator />
          <div>
            <div class="text-subtitle1 text-weight-medium">
              {{ t('harnesses.catalog.connectionTitle') }}
            </div>
            <div class="text-caption text-grey-7">
              {{ t('harnesses.catalog.connectionHint') }}
            </div>
          </div>

          <q-input
            v-model="form.base_url"
            filled
            :readonly="!canEdit || busy"
            :label="t('harnesses.catalog.baseUrl')"
            :rules="[requiredRule]"
            @update:model-value="connectionTested = false"
          />
          <q-input
            v-model="form.token"
            filled
            :readonly="!canEdit || busy"
            :type="showToken ? 'text' : 'password'"
            :label="t('harnesses.catalog.token')"
            :hint="tokenConfigured && !form.token
              ? t('harnesses.catalog.tokenRetained')
              : undefined"
            @update:model-value="connectionTested = false"
          >
            <template #append>
              <q-icon
                :name="showToken ? 'visibility_off' : 'visibility'"
                class="cursor-pointer"
                @click="showToken = !showToken"
              />
            </template>
          </q-input>

          <div class="row items-center q-gutter-md">
            <q-btn
              outline
              color="primary"
              icon="network_check"
              :label="t('harnesses.catalog.testConnection')"
              :loading="testing"
              :disable="!canEdit || busy || !form.base_url.trim()"
              @click="testConnection"
            />
            <q-chip
              v-if="connectionTested"
              color="positive"
              text-color="white"
              icon="check_circle"
            >
              {{ t('harnesses.catalog.connectionOk') }}
            </q-chip>
          </div>

          <q-select
            v-model="form.model"
            :options="modelOptions"
            filled
            clearable
            :readonly="!canEdit || busy"
            :disable="!modelOptions.length"
            :label="t('harnesses.catalog.model')"
            :hint="modelOptions.length
              ? t('harnesses.catalog.modelHint')
              : t('harnesses.catalog.testFirst')"
            :rules="[requiredRule]"
          />
        </template>

        <q-banner v-if="entry?.last_error" rounded class="bg-red-1 text-negative">
          {{ entry.last_error }}
        </q-banner>

        <div class="row items-center q-gutter-sm" :class="{ 'galaris-dialog-actions': embedded }">
          <q-space />
          <q-btn v-if="embedded" flat :label="t('common.cancel')" @click="emit('close')" />
          <q-btn
            v-if="!isNew && isOpenAi && canEdit"
            flat
            color="negative"
            icon="delete"
            :label="t('harnesses.catalog.delete')"
            :disable="busy"
            @click="deleteDialog = true"
          />
          <q-btn
            v-if="canEdit && isOpenAi"
            type="submit"
            color="primary"
            icon="save"
            :label="t('common.save')"
            :loading="saving"
            :disable="!canSave || busy"
          />
        </div>
      </q-form>
      <HarnessProviderSettings
        v-if="!loading && !loadFailed && entry && !isOpenAi"
        :key="entry.provider_code"
        :provider="entry.provider_code"
      />
    </q-card>

    <q-dialog v-model="disableDialog">
      <q-card class="harness-detail__confirm">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ t('harnesses.catalog.disableTitle') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section>
          {{ t('harnesses.catalog.disableConfirm', {
            name: form.name,
            count: entry?.assigned_agents ?? 0,
          }) }}
        </q-card-section>
        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn v-close-popup flat color="grey-7" :label="t('common.cancel')" />
          <q-btn
            color="warning"
            :label="t('harnesses.catalog.disable')"
            :loading="activationBusy"
            @click="confirmDisable"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="deleteDialog">
      <q-card class="harness-detail__confirm">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ t('harnesses.catalog.deleteTitle') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section>
          {{ t('harnesses.catalog.deleteConfirm', {
            name: form.name,
            count: entry?.assigned_agents ?? 0,
          }) }}
        </q-card-section>
        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn v-close-popup flat color="grey-7" :label="t('common.cancel')" />
          <q-btn
            color="negative"
            :label="t('common.delete')"
            :loading="deleting"
            @click="remove"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
    <div v-if="!embedded" class="q-mt-md">
      <q-btn flat color="primary" icon="arrow_back" :label="t('common.back')" :to="isOpenAi ? '/params/harnesses?tab=external' : '/params/harnesses'" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { privileges, usePrivilegeStore } from '@/core/authorize'
import { PageHeader } from '@/core/util'
import { HarnessProviderSettings } from '@/core/params'
import { harnessBrand } from '../branding'
import {
  harnessService,
  type HarnessCatalogEntry,
  type HarnessCatalogUpdate,
} from '../services/harnessService'

const props = defineProps<{ harnessId?: string; embedded?: boolean }>()
const emit = defineEmits<{
  close: []
  done: []
  mutation: [completion: Promise<HarnessCatalogEntry | string>]
}>()
const route = useRoute()
const router = useRouter()
const $q = useQuasar()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.PARAMS_EDIT))
const harnessId = computed(() => props.harnessId ?? String(route.params.id ?? ''))
const isNew = computed(() => harnessId.value === 'new')
const bridgeProviderCode = computed(() => (
  harnessId.value.startsWith('bridge-') ? harnessId.value.slice('bridge-'.length) : null
))
const persistedHarnessId = computed(() => entry.value?.id ?? harnessId.value)
const isOpenAi = computed(() => isNew.value || entry.value?.provider_code === 'openai_messages')
const galarisModelProviders = new Set([
  'claude_agent',
  'codex',
  'deepseek_harness',
])
const usesGalarisModels = computed(() => galarisModelProviders.has(
  entry.value?.provider_code ?? '',
))
const loading = ref(false)
const loadFailed = ref(false)
const saving = ref(false)
const testing = ref(false)
const deleting = ref(false)
const activationBusy = ref(false)
const busy = computed(() => saving.value || testing.value || deleting.value || activationBusy.value)
const disableDialog = ref(false)
const deleteDialog = ref(false)
const connectionTested = ref(false)
const showToken = ref(false)
const tokenConfigured = ref(false)
const modelOptions = ref<string[]>([])
const entry = ref<HarnessCatalogEntry | null>(null)
const form = reactive({
  name: '',
  enabled: false,
  base_url: '',
  token: '',
  model: null as string | null,
  settings: {} as Record<string, unknown>,
})
const providerLabel = computed(() => entry.value?.provider_label ?? 'OpenAI Messages')
const providerIcon = computed(() => harnessBrand(
  entry.value?.provider_code ?? 'openai_messages',
).icon)
const canSave = computed(() => (
  form.name.trim().length > 0
  && (!isOpenAi.value || (form.base_url.trim().length > 0 && Boolean(form.model)))
))

function requiredRule(value: string | null): true | string {
  return Boolean(value?.trim()) || t('harnesses.catalog.required')
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
    ?? fallback
}

function applyEntry(data: HarnessCatalogEntry): void {
  entry.value = data
  form.name = data.name
  form.enabled = data.enabled
  form.base_url = data.base_url ?? ''
  form.model = data.model
  form.settings = { ...data.settings }
  tokenConfigured.value = data.token_configured
  modelOptions.value = data.model ? [data.model] : []
}

let loadRevision = 0

async function load(): Promise<void> {
  const revision = ++loadRevision
  const id = harnessId.value
  const provider = bridgeProviderCode.value
  entry.value = null
  Object.assign(form, { name: '', enabled: false, base_url: '', token: '', model: null, settings: {} })
  tokenConfigured.value = false
  showToken.value = false
  connectionTested.value = false
  modelOptions.value = []
  disableDialog.value = false
  deleteDialog.value = false
  loading.value = false
  loadFailed.value = false
  saving.value = false
  testing.value = false
  deleting.value = false
  activationBusy.value = false
  if (isNew.value) {
    form.name = t('harnesses.catalog.defaultApiName')
    return
  }
  loading.value = true
  try {
    if (provider) {
      const bridge = (await harnessService.catalog()).data.find(
        item => item.provider_code === provider,
      )
      if (revision !== loadRevision) return
      if (!bridge) throw new Error(t('harnesses.catalog.loadError'))
      applyEntry(bridge)
    } else {
      const response = await harnessService.catalogEntry(id)
      if (revision !== loadRevision) return
      applyEntry(response.data)
    }
  } catch (error: unknown) {
    if (revision !== loadRevision) return
    $q.notify({
      type: 'negative',
      message: errorDetail(error, t('harnesses.catalog.loadError')),
    })
    if (props.embedded) loadFailed.value = true
    else await router.replace(isOpenAi.value ? '/params/harnesses?tab=external' : '/params/harnesses')
  } finally {
    if (revision === loadRevision) loading.value = false
  }
}

async function testConnection(): Promise<void> {
  if (!canEdit.value || busy.value) return
  const revision = loadRevision
  const address = form.base_url
  const token = form.token
  testing.value = true
  connectionTested.value = false
  try {
    const data = (await harnessService.probe({
      harness_id: isNew.value ? undefined : persistedHarnessId.value,
      base_url: form.base_url.trim(),
      token: form.token.trim() || undefined,
    })).data
    if (revision !== loadRevision || form.base_url !== address || form.token !== token) return
    form.base_url = data.base_url
    modelOptions.value = data.models
    if (!form.model || !data.models.includes(form.model)) {
      form.model = data.models[0] ?? null
    }
    connectionTested.value = true
    $q.notify({ type: 'positive', message: t('harnesses.catalog.connectionOk') })
  } catch (error: unknown) {
    if (revision !== loadRevision) return
    $q.notify({
      type: 'negative',
      message: errorDetail(error, t('harnesses.catalog.connectionError')),
    })
  } finally {
    if (revision === loadRevision) testing.value = false
  }
}

function persistedUpdate(enabled: boolean): HarnessCatalogUpdate | null {
  if (!entry.value) return null
  return {
    name: entry.value.name,
    enabled,
    base_url: entry.value.base_url,
    model: entry.value.model,
    settings: entry.value.settings,
  }
}

async function persistEnabled(enabled: boolean): Promise<void> {
  if (!canEdit.value || busy.value) return
  const payload = persistedUpdate(enabled)
  if (!payload) return
  const revision = loadRevision
  activationBusy.value = true
  try {
    const operation = harnessService.updateCatalogEntry(persistedHarnessId.value, payload).then(result => result.data)
    emit('mutation', operation)
    const updated = await operation
    if (revision !== loadRevision) return
    // Activation must not erase unsaved connection edits.
    entry.value = updated
    form.enabled = updated.enabled
    $q.notify({
      type: 'positive',
      message: t(enabled
        ? 'harnesses.catalog.activated'
        : 'harnesses.catalog.deactivated'),
    })
  } catch (error: unknown) {
    if (revision !== loadRevision) return
    $q.notify({
      type: 'negative',
      message: errorDetail(error, t('harnesses.catalog.activationError')),
    })
  } finally {
    if (revision === loadRevision) activationBusy.value = false
  }
}

function requestEnabledChange(enabled: boolean): void {
  if (!canEdit.value || busy.value) return
  if (isNew.value) {
    form.enabled = enabled
  } else if (enabled) {
    void persistEnabled(true)
  } else {
    disableDialog.value = true
  }
}

async function confirmDisable(): Promise<void> {
  const revision = loadRevision
  await persistEnabled(false)
  if (revision === loadRevision) disableDialog.value = false
}

async function save(): Promise<void> {
  if (!isOpenAi.value || !canEdit.value || !canSave.value || busy.value) return
  const revision = loadRevision
  saving.value = true
  try {
    const payload: HarnessCatalogUpdate = {
      name: form.name.trim(),
      enabled: form.enabled,
      base_url: isOpenAi.value ? form.base_url.trim() : entry.value?.base_url ?? null,
      token: form.token.trim() || undefined,
      model: isOpenAi.value ? form.model : entry.value?.model ?? null,
      settings: form.settings,
    }
    if (isNew.value) {
      const operation = harnessService.createCatalogEntry({
        provider_code: 'openai_messages',
        ...payload,
      }).then(result => result.data)
      emit('mutation', operation)
      const created = await operation
      if (revision !== loadRevision) return
      applyEntry(created)
      $q.notify({ type: 'positive', message: t('harnesses.catalog.added') })
      if (!props.embedded) await router.replace(`/harnesses/${created.id}`)
    } else {
      const operation = harnessService.updateCatalogEntry(persistedHarnessId.value, payload).then(result => result.data)
      emit('mutation', operation)
      const updated = await operation
      if (revision !== loadRevision) return
      applyEntry(updated)
      form.token = ''
      $q.notify({ type: 'positive', message: t('harnesses.catalog.saved') })
    }
    emit('done')
  } catch (error: unknown) {
    if (revision !== loadRevision) return
    $q.notify({
      type: 'negative',
      message: errorDetail(error, t('harnesses.catalog.saveError')),
    })
  } finally {
    if (revision === loadRevision) saving.value = false
  }
}

async function remove(): Promise<void> {
  if (isNew.value || !canEdit.value || busy.value) return
  const revision = loadRevision
  const id = persistedHarnessId.value
  deleting.value = true
  try {
    const operation = harnessService.deleteCatalogEntry(id).then(() => id)
    emit('mutation', operation)
    await operation
    if (revision !== loadRevision) return
    $q.notify({ type: 'positive', message: t('harnesses.catalog.deleted') })
    if (props.embedded) emit('done')
    else await router.replace(isOpenAi.value ? '/params/harnesses?tab=external' : '/params/harnesses')
  } catch (error: unknown) {
    if (revision !== loadRevision) return
    $q.notify({
      type: 'negative',
      message: errorDetail(error, t('harnesses.catalog.deleteError')),
    })
  } finally {
    if (revision === loadRevision) {
      deleting.value = false
      deleteDialog.value = false
    }
  }
}

watch(harnessId, load, { immediate: true })
onBeforeUnmount(() => { loadRevision++ })
</script>

<style scoped>
.harness-detail { min-width: 0; }
.harness-detail__card { max-width: 1280px; }
.harness-detail__confirm { width: 580px; max-width: 92vw; }
</style>
