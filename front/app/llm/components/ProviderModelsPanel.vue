<template>
  <section class="provider-models-panel column no-wrap">
    <div class="provider-panel-header row items-center q-pa-md">
      <div class="col">
        <div class="text-subtitle1 text-weight-bold">{{ t('llm.availableResources') }}</div>
        <div class="text-caption text-grey-7">
          {{ canLoad
            ? t('llm.resourcesForProvider', { name: item?.display_name, count: models.length })
            : t('llm.activateToDiscoverModels') }}
        </div>
      </div>
      <q-btn
        v-if="canEdit && item?.supports_model_management && item.connection?.is_active"
        round
        flat
        color="primary"
        icon="download"
        :aria-label="t('llm.addModel')"
        @click="pullDialog = true"
      >
        <q-tooltip>{{ t('llm.addModel') }}</q-tooltip>
      </q-btn>
      <q-btn
        round
        flat
        color="primary"
        icon="refresh"
        :loading="loading"
        :disable="!canLoad"
        :aria-label="t('common.refresh')"
        @click="emit('refresh')"
      >
        <q-tooltip>{{ t('common.refresh') }}</q-tooltip>
      </q-btn>
    </div>

    <div
      v-if="item?.capabilities.length"
      class="resource-category q-pa-sm"
    >
      <q-select
        v-model="selectedCapability"
        :options="capabilityOptions"
        :label="t('llm.resourceCategory')"
        dense
        outlined
        emit-value
        map-options
        behavior="menu"
      >
        <template #prepend>
          <q-icon :name="capabilityMeta(capability).icon" class="resource-category-icon" />
        </template>
        <template #option="scope">
          <q-item v-bind="scope.itemProps">
            <q-item-section avatar>
              <q-icon :name="scope.opt.icon" class="resource-category-icon" />
            </q-item-section>
            <q-item-section>{{ scope.opt.label }}</q-item-section>
          </q-item>
        </template>
      </q-select>
      <div v-if="capability === 'documents'" class="text-caption text-grey-7 q-mt-xs">
        {{ t('llm.documentResourcesHint') }}
      </div>
    </div>

    <div v-if="canLoad" class="q-pa-sm model-search column">
      <q-input
        v-model="search"
        dense
        outlined
        clearable
        :placeholder="t('llm.searchResources')"
      >
        <template #prepend><q-icon name="search" /></template>
      </q-input>

      <q-input
        v-model="manualModelId"
        dense
        outlined
        clearable
        :label="t('llm.manualResourceId')"
        :disable="!canEdit"
        @keyup.enter="requestManualCreate"
      >
        <template #prepend><q-icon name="edit_note" /></template>
        <template #append>
          <q-btn
            v-if="canEdit"
            round
            flat
            dense
            color="primary"
            icon="add"
            :disable="manualModelDisabled"
            :aria-label="t('llm.createManualLlm')"
            @click="requestManualCreate"
          >
            <q-tooltip>{{ t('llm.createManualLlm') }}</q-tooltip>
          </q-btn>
        </template>
      </q-input>

      <div v-if="models.length" class="row q-gutter-xs">
        <q-chip v-if="voiceResourceCount" dense square icon="record_voice_over" color="deep-purple-1" text-color="deep-purple-9">
          {{ t('llm.voices') }} · {{ voiceResourceCount }}
        </q-chip>
      </div>
    </div>

    <q-scroll-area v-if="error || emptyState" class="col">
      <div v-if="error" class="q-pa-md">
        <q-banner rounded class="bg-red-1 text-red-10">
          <template #avatar><q-icon name="cloud_off" /></template>
          <div>{{ error }}</div>
          <q-btn flat dense color="negative" :label="t('common.retry')" @click="emit('refresh')" />
        </q-banner>
      </div>

      <div v-else-if="emptyState" class="column flex-center text-center text-grey-6 q-pa-xl model-empty">
        <q-icon :name="emptyState.icon" size="50px" class="q-mb-md" />
        <div class="text-subtitle1 text-weight-medium">{{ emptyState.title }}</div>
        <div class="text-caption q-mt-xs" style="max-width: 320px">{{ emptyState.hint }}</div>
      </div>

    </q-scroll-area>

    <div v-else-if="loading" class="col column flex-center" role="status">
      <q-spinner color="primary" size="34px" />
      <span class="text-caption q-mt-sm">{{ t('llm.loading') }}</span>
    </div>

    <q-scroll-area
      v-else
      ref="modelScrollArea"
      visible
      class="col resource-scroll-area"
      :thumb-style="{ width: '8px', borderRadius: '4px', backgroundColor: 'var(--q-primary)', opacity: '0.65' }"
    >
      <q-virtual-scroll
        v-slot="{ item: model }"
        class="resource-virtual-scroll"
        :scroll-target="modelScrollArea?.getScrollTarget()"
        :items="sortedFilteredModels"
        :virtual-scroll-item-size="112"
        separator
      >
        <q-item :key="model.id" class="model-item q-py-md">
          <q-item-section>
            <div class="row items-start no-wrap q-gutter-sm">
              <div class="col model-copy">
                <div class="row items-center q-gutter-xs">
                  <span class="text-weight-bold model-name">{{ model.name || model.id }}</span>
                  <q-badge v-if="model.resource_type === 'voice'" color="purple" outline>
                    {{ t('llm.voice') }}
                  </q-badge>
                  <q-badge v-if="model.status" color="warning" outline>{{ model.status }}</q-badge>
                </div>
                <div v-if="model.name && model.name !== model.id" class="text-caption text-grey-7 ellipsis">
                  {{ model.id }}
                </div>
                <div v-if="model.description" class="text-caption text-grey-7 q-mt-xs" lines="2">
                  {{ model.description }}
                </div>

                <div class="row items-center q-gutter-xs q-mt-sm">
                  <q-chip v-if="model.context_length" dense square color="blue-grey-1" text-color="blue-grey-9" icon="data_object">
                    {{ formatContext(model.context_length) }}
                  </q-chip>
                  <q-chip v-if="model.capabilities?.tools" dense square outline color="primary" icon="construction">
                    {{ t('llm.capabilityTools') }}
                  </q-chip>
                  <q-chip v-if="model.capabilities?.reasoning" dense square outline color="deep-purple" icon="psychology">
                    {{ t('llm.capabilityReasoning') }}
                  </q-chip>
                  <q-chip
                    v-for="serviceCapability in model.service_capabilities"
                    :key="`service-${serviceCapability}`"
                    dense
                    square
                    outline
                    :icon="capabilityMeta(serviceCapability).icon"
                    :color="capabilityMeta(serviceCapability).color"
                    :style="serviceCapability === 'decision' ? { color: 'var(--solaire-blue-accent)' } : undefined"
                  >
                    {{ capabilityMeta(serviceCapability).label }}
                  </q-chip>
                  <q-chip
                    v-for="badge in modalityBadges(model)"
                    :key="badge.key"
                    dense
                    square
                    outline
                    :color="badge.color"
                  >
                    {{ badge.label }}
                    <q-tooltip>{{ badge.tip }}</q-tooltip>
                  </q-chip>
                </div>

                <div v-if="model.pricing" class="row q-col-gutter-sm q-mt-sm model-pricing">
                  <div v-if="hasPrice(model.pricing.input)" class="col-auto">
                    <span class="text-caption text-grey-7">{{ t('llm.costInShort') }}</span>
                    <strong class="q-ml-xs">{{ formatPrice(model.pricing.input) }}</strong>
                  </div>
                  <div v-if="hasPrice(model.pricing.cached_input)" class="col-auto">
                    <span class="text-caption text-grey-7">{{ t('llm.costCacheShort') }}</span>
                    <strong class="q-ml-xs">{{ formatPrice(model.pricing.cached_input) }}</strong>
                  </div>
                  <div v-if="hasPrice(model.pricing.cache_write)" class="col-auto">
                    <span class="text-caption text-grey-7">{{ t('llm.costCacheWriteShort') }}</span>
                    <strong class="q-ml-xs">{{ formatPrice(model.pricing.cache_write) }}</strong>
                  </div>
                  <div v-if="hasPrice(model.pricing.output)" class="col-auto">
                    <span class="text-caption text-grey-7">{{ t('llm.costOutShort') }}</span>
                    <strong class="q-ml-xs">{{ formatPrice(model.pricing.output) }}</strong>
                  </div>
                  <div
                    v-for="entry in additionalPricing(model.pricing)"
                    :key="entry.key"
                    class="col-auto"
                  >
                    <span class="text-caption text-grey-7">{{ entry.label }}</span>
                    <strong class="q-ml-xs">{{ entry.value }}</strong>
                  </div>
                </div>
              </div>

              <div class="column items-center q-gutter-xs">
                <q-btn
                  v-if="canEdit"
                  round
                  unelevated
                  :color="isConfigured(model.id) ? 'positive' : 'primary'"
                  :icon="isConfigured(model.id) ? 'check' : 'add'"
                  size="sm"
                  :disable="isConfigured(model.id) || !item?.connection"
                  @click="emit('create-llm', model)"
                >
                  <q-tooltip>
                    {{ !item?.connection
                      ? t('llm.configureProviderFirst')
                      : (isConfigured(model.id) ? t('llm.modelAlreadyConfigured') : t('llm.createLlmFromModel')) }}
                  </q-tooltip>
                </q-btn>
                <q-btn
                  v-if="canEdit && item?.supports_model_management"
                  round
                  flat
                  color="negative"
                  icon="delete"
                  size="sm"
                  @click="confirmDelete(model.id)"
                >
                  <q-tooltip>{{ t('llm.deleteModelTooltip') }}</q-tooltip>
                </q-btn>
              </div>
            </div>
          </q-item-section>
        </q-item>
      </q-virtual-scroll>
    </q-scroll-area>

    <q-dialog v-model="pullDialog">
      <q-card style="width: 520px; max-width: 92vw">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ t('llm.addModelFor', { name: item?.display_name }) }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="$t('common.close')" />
        </q-card-section>
        <q-card-section>
          <q-input
            v-model="pullModelName"
            autofocus
            outlined
            :label="t('llm.modelName')"
            :hint="t('llm.modelNameHint')"
            @keyup.enter="requestPull"
          />
          <div class="text-caption text-grey-7 q-mt-md">{{ t('llm.downloadHint') }}</div>
        </q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn
            v-if="canEdit"
            color="primary"
            icon="download"
            :label="t('llm.download')"
            :disable="!pullModelName.trim()"
            :loading="managing"
            @click="requestPull"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="deleteDialog">
      <q-card style="width: 480px; max-width: 92vw">
        <q-card-section class="galaris-dialog-title">
          <div class="text-h6">{{ t('common.confirm') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="$t('common.close')" />
        </q-card-section>
        <q-card-section>
          {{ t('llm.deleteModelConfirm', { model: modelToDelete, provider: item?.display_name }) }}
          <div class="text-negative text-caption q-mt-sm">{{ t('llm.deleteModelWarning') }}</div>
        </q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn
            v-if="canEdit"
            color="negative"
            :label="t('llm.deleteFromServer')"
            :loading="managing"
            @click="requestDelete"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, useTemplateRef, watch } from 'vue'
import type { QScrollArea } from 'quasar'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import type { LLMModelInfo, LLMWithProvider, ProviderCatalogItem } from '../services/llmProviderService'
import { providerResourceCategories, providerResourceCapability, type ProviderResourceCategory } from '../providerUi'

const props = defineProps<{
  item: ProviderCatalogItem | null
  capability: ProviderResourceCategory
  models: LLMModelInfo[]
  configuredLlms: LLMWithProvider[]
  loading?: boolean
  managing?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  refresh: []
  'update:capability': [capability: ProviderResourceCategory]
  'create-llm': [model: LLMModelInfo]
  pull: [modelName: string]
  'delete-model': [modelName: string]
}>()

const { t, locale } = useI18n()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.LLM_PROVIDER_EDIT))
const selectedCapability = computed({
  get: () => props.capability,
  set: (value: ProviderResourceCategory) => emit('update:capability', value),
})
const search = ref<string | null>('')
const modelScrollArea = useTemplateRef<QScrollArea>('modelScrollArea')
const manualModelId = ref<string | null>('')
const pullDialog = ref(false)
const pullModelName = ref('')
const deleteDialog = ref(false)
const modelToDelete = ref('')

const canLoad = computed(() => Boolean(
  props.item
  && (
    (props.item.connection
      && (props.item.auth_type !== 'oauth_device' || props.item.connection.oauth_connected))
    || (!props.item.connection && !props.item.is_custom && props.item.auth_type === 'optional_api_key')
  ),
))
const manualModelValue = computed(() => manualModelId.value?.trim() || '')
const manualModelDisabled = computed(() => (
  !props.item?.connection || !manualModelValue.value || isConfigured(manualModelValue.value)
))
const capabilityOptions = computed(() => providerResourceCategories(props.item?.capabilities || []).map(value => ({
  value,
  ...capabilityMeta(value),
})))

const filteredModels = computed(() => {
  const needle = search.value?.trim().toLowerCase() || ''
  if (!needle) return props.models
  return props.models.filter(model =>
    model.id.toLowerCase().includes(needle)
    || model.name?.toLowerCase().includes(needle)
    || model.description?.toLowerCase().includes(needle),
  )
})
const sortedFilteredModels = computed(() => [...filteredModels.value].sort((left, right) => (
  Number(left.resource_type === 'voice') - Number(right.resource_type === 'voice')
  || (left.name || left.id).localeCompare(right.name || right.id)
)))
const voiceResourceCount = computed(() => props.models.filter(resource => resource.resource_type === 'voice').length)

const emptyState = computed(() => {
  if (!props.item) {
    return { icon: 'touch_app', title: t('llm.selectProvider'), hint: t('llm.selectProviderModelsHint') }
  }
  if (!props.item.connection && props.item.auth_type !== 'optional_api_key') {
    return { icon: 'power_settings_new', title: t('llm.providerNotConfigured'), hint: t('llm.configureProviderFirst') }
  }
  if (props.item.auth_type === 'oauth_device' && !props.item.connection?.oauth_connected) {
    return { icon: 'login', title: t('llm.authenticationRequired'), hint: t('llm.connectSubscriptionFirst') }
  }
  if (!props.loading && !props.models.length) {
    return { icon: 'smart_toy', title: t('llm.noModelAvailable'), hint: t('llm.refreshModelsHint') }
  }
  if (!props.loading && props.models.length && !filteredModels.value.length) {
    return { icon: 'search_off', title: t('llm.noModelFound'), hint: t('llm.changeModelSearch') }
  }
  return null
})

function isConfigured(modelId: string): boolean {
  const providerId = props.item?.connection?.id
  return props.configuredLlms.some(llm =>
    llm.llm_provider_id === providerId && llm.llm_name === modelId,
  )
}

function requestManualCreate(): void {
  if (!canEdit.value) return
  const id = manualModelValue.value
  if (!id || isConfigured(id)) return
  emit('create-llm', {
    id,
    name: null,
    description: null,
    context_length: null,
    pricing: null,
    resource_type: 'model',
    service_capabilities: [providerResourceCapability(props.capability)],
  })
}

watch(
  () => props.item?.key,
  () => {
    search.value = ''
    manualModelId.value = ''
  },
)

function hasPrice(value: unknown): boolean {
  if (value === null || value === undefined || value === '') return false
  return Number.isFinite(typeof value === 'number' ? value : Number(value))
}

function formatPrice(value: unknown): string {
  const amount = typeof value === 'number' ? value : Number(value)
  return `${new Intl.NumberFormat(locale.value, {
    style: 'currency',
    currency: 'USD',
    currencyDisplay: 'narrowSymbol',
    maximumFractionDigits: 6,
  }).format(amount)} / 1M`
}

function formatContext(value: number): string {
  return `${new Intl.NumberFormat(locale.value, { notation: 'compact' }).format(value)} tokens`
}

function additionalPricing(pricing: Record<string, unknown>): { key: string; label: string; value: string }[] {
  const ignored = new Set(['input', 'cached_input', 'cache_write', 'output', 'unit'])
  const result: { key: string; label: string; value: string }[] = []
  const lines = Array.isArray(pricing.lines) ? pricing.lines : []
  for (const [index, raw] of lines.entries()) {
    if (!raw || typeof raw !== 'object') continue
    const line = raw as Record<string, unknown>
    const cost = Number(line.cost_usd)
    if (!Number.isFinite(cost)) continue
    result.push({
      key: `line-${index}`,
      label: String(line.billable || t('llm.price')),
      value: `${formatCurrency(cost)} / ${String(line.unit || t('llm.unit'))}`,
    })
  }
  for (const [key, raw] of Object.entries(pricing)) {
    if (ignored.has(key) || key === 'lines' || raw === null || raw === undefined) continue
    if (typeof raw !== 'number' && typeof raw !== 'string') continue
    result.push({
      key,
      label: t(`llm.pricing.${key}`),
      value: `${raw}${pricing.unit ? ` / ${String(pricing.unit)}` : ''}`,
    })
  }
  return result
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat(locale.value, {
    style: 'currency',
    currency: 'USD',
    currencyDisplay: 'narrowSymbol',
    maximumFractionDigits: 8,
  }).format(value)
}

function modalityBadges(model: LLMModelInfo): { key: string; label: string; color: string; tip: string }[] {
  const values = model.modalities as unknown as Record<string, boolean> | null | undefined
  if (!values) return []
  const labels: Record<string, string> = { image: 'I', file: 'F', video: 'V', audio: 'A' }
  const result: { key: string; label: string; color: string; tip: string }[] = []
  for (const direction of ['input', 'output'] as const) {
    for (const name of ['image', 'file', 'video', 'audio'] as const) {
      const key = `${direction}_${name}`
      if (!values[key]) continue
      result.push({
        key,
        label: labels[name],
        color: direction === 'input' ? 'primary' : 'teal',
        tip: `${direction === 'input' ? t('llm.input') : t('llm.output')} · ${t(`llm.${name}`)}`,
      })
    }
  }
  return result
}

function capabilityMeta(capability: ProviderResourceCategory): { label: string; icon: string; color: string } {
  const values: Record<ProviderResourceCategory, { label: string; icon: string; color: string }> = {
    documents: { label: t('llm.documentResources'), icon: 'description', color: 'primary' },
    chat: { label: t('llm.capabilities.chat'), icon: 'chat', color: 'primary' },
    vision: { label: t('llm.capabilities.vision'), icon: 'visibility', color: 'blue' },
    image_generation: { label: t('llm.capabilities.image_generation'), icon: 'image', color: 'pink' },
    embedding: { label: t('llm.capabilities.embedding'), icon: 'scatter_plot', color: 'indigo' },
    decision: { label: t('llm.capabilities.decision'), icon: 'alt_route', color: '' },
    transcription: { label: t('llm.capabilities.transcription'), icon: 'graphic_eq', color: 'orange' },
    speech: { label: t('llm.capabilities.speech'), icon: 'record_voice_over', color: 'purple' },
    realtime_conversation: { label: t('llm.capabilities.realtime_conversation'), icon: 'spatial_audio', color: 'teal' },
    audio_understanding: { label: t('llm.capabilities.audio_understanding'), icon: 'hearing', color: 'blue' },
    video_understanding: { label: t('llm.capabilities.video_understanding'), icon: 'movie', color: 'deep-orange' },
    sound_generation: { label: t('llm.capabilities.sound_generation'), icon: 'surround_sound', color: 'orange' },
    music_generation: { label: t('llm.capabilities.music_generation'), icon: 'music_note', color: 'purple' },
    video_generation: { label: t('llm.capabilities.video_generation'), icon: 'video_library', color: 'deep-orange' },
  }
  return values[capability]
}

function requestPull(): void {
  if (!canEdit.value) return
  const modelName = pullModelName.value.trim()
  if (!modelName) return
  emit('pull', modelName)
  pullDialog.value = false
  pullModelName.value = ''
}

function confirmDelete(modelName: string): void {
  if (!canEdit.value) return
  modelToDelete.value = modelName
  deleteDialog.value = true
}

function requestDelete(): void {
  if (!canEdit.value) return
  if (!modelToDelete.value) return
  emit('delete-model', modelToDelete.value)
  deleteDialog.value = false
  modelToDelete.value = ''
}
</script>

<style scoped>
.provider-models-panel {
  height: clamp(640px, calc(100vh - 210px), 900px);
  min-height: 640px;
  max-height: 900px;
  min-width: 0;
  overflow: hidden;
  position: relative;
  background: color-mix(in srgb, var(--q-primary) 1.5%, transparent);
}

.resource-scroll-area {
  min-height: 0;
}

.resource-scroll-area :deep(.q-scrollarea__container) {
  overscroll-behavior: contain;
}

.resource-virtual-scroll {
  overflow: visible;
  padding-right: 12px;
}

.provider-panel-header,
.resource-category,
.model-search {
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}

.provider-panel-header {
  gap: 8px;
}

.resource-category-icon {
  color: var(--solaire-blue-accent);
}

.model-search {
  gap: 8px;
}

.model-empty {
  min-height: 420px;
}

.model-item {
  min-height: 112px;
}

.model-copy {
  min-width: 0;
}

.model-name {
  overflow-wrap: anywhere;
}

.model-pricing {
  font-size: 0.72rem;
}

body.body--dark .provider-panel-header,
body.body--dark .resource-category,
body.body--dark .model-search {
  border-color: rgba(255, 255, 255, 0.12);
}

@media (min-width: 1280px) {
  .provider-models-panel {
    height: 100%;
    min-height: 0;
    max-height: none;
  }

  .provider-panel-header,
  .resource-category,
  .model-search {
    flex-shrink: 0;
  }
}

@media (max-width: 1279px) {
  .provider-models-panel {
    height: min(720px, calc(100svh - 32px));
    min-height: 520px;
    max-height: none;
  }

  .model-item {
    padding-right: 8px;
    padding-left: 8px;
  }
}
</style>
