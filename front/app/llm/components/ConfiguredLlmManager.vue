<template>
  <section class="configured-llm-manager">
    <div class="configured-llm-toolbar row items-center q-mb-md" :class="{ 'justify-end': !showHeading }">
      <div v-if="showHeading" class="col">
        <div class="text-h5">{{ t('llm.myLlms') }}</div>
        <div class="text-caption text-grey-7">{{ t('llm.myLlmsHint') }}</div>
      </div>
      <div v-if="canEdit" class="llm-toolbar-actions row">
        <q-btn
          outline
          color="secondary"
          icon="fact_check"
          :label="t('llm.checkAll')"
          :loading="checkingAll"
          :disable="initializing || checkingLlmId !== null"
          @click="checkAllLlms"
        />
        <q-btn
          color="primary"
          icon="add"
          :label="t('llm.addLlm')"
          :loading="initializing"
          @click="openCreate"
        />
      </div>
    </div>

    <q-table
      class="configured-llm-table"
      :rows="llmsWithProviderNames"
      :columns="columns"
      :loading="store.loadingLLMs"
      row-key="id"
      flat
      bordered
      :grid="$q.screen.lt.md"
      :rows-per-page-options="[10, 20, 50, 100, 500]"
      :pagination="{ rowsPerPage: 50 }"
    >
      <template #body-cell-status="{ row }">
        <q-td class="text-center">
          <q-icon
            v-if="availability.has(row.id)"
            :name="availability.get(row.id) ? 'check_circle' : 'error'"
            :color="availability.get(row.id) ? 'positive' : 'negative'"
            size="sm"
          >
            <q-tooltip>{{ availability.get(row.id) ? t('llm.available') : t('llm.unavailable') }}</q-tooltip>
          </q-icon>
          <q-icon v-else name="help" color="grey-6" size="sm">
            <q-tooltip>{{ t('llm.unknownStatus') }}</q-tooltip>
          </q-icon>
        </q-td>
      </template>

      <template #body-cell-provider_name="{ row }">
        <q-td>
          <q-badge color="secondary" outline>{{ row.provider_name }}</q-badge>
        </q-td>
      </template>

      <template #body-cell-primary_capability="{ row }">
        <q-td>
          <div class="llm-badges row">
            <q-badge
              v-for="capability in configuredCapabilities(row)"
              :key="capability"
              :style="{ color: solaireCss.blue.accent }"
              outline
            >
              {{ capabilityMeta(capability).label }}
            </q-badge>
          </div>
        </q-td>
      </template>

      <template #body-cell-llm_metrics="{ row }">
        <q-td>
          <div class="column q-gutter-xs">
            <span v-if="hasContext(row.context_length)" class="text-caption text-grey-7">
              {{ formatContext(row.context_length) }}
            </span>
            <div class="llm-badges row">
              <q-badge v-if="row.is_subscription" color="green" outline>
                {{ t('llm.subscriptionBadge') }}
              </q-badge>
              <q-badge v-if="hasPrice(row.cost_per_input_token)" color="primary" outline>
                {{ t('llm.costInShort') }} {{ formatPrice(row.cost_per_input_token) }}
              </q-badge>
              <q-badge v-if="hasPrice(row.cost_per_cached_input_token)" color="indigo" outline>
                {{ t('llm.costCacheShort') }} {{ formatPrice(row.cost_per_cached_input_token) }}
              </q-badge>
              <q-badge v-if="hasPrice(row.cost_per_output_token)" color="teal" outline>
                {{ t('llm.costOutShort') }} {{ formatPrice(row.cost_per_output_token) }}
              </q-badge>
            </div>
          </div>
        </q-td>
      </template>

      <template #body-cell-actions="{ row }">
        <q-td class="text-right">
          <q-btn
            v-if="canEdit"
            flat
            round
            color="secondary"
            icon="fact_check"
            size="sm"
            :loading="checkingLlmId === row.id"
            :disable="checkingAll || checkingLlmId !== null"
            :aria-label="t('llm.checkOne')"
            @click="checkOneLlm(row)"
          >
            <q-tooltip>{{ t('llm.checkOne') }}</q-tooltip>
          </q-btn>
          <q-btn v-if="canEdit" flat round color="primary" icon="edit" size="sm" :aria-label="t('common.edit')" @click="openEdit(row)">
            <q-tooltip>{{ t('common.edit') }}</q-tooltip>
          </q-btn>
          <q-btn v-if="canEdit" flat round color="negative" icon="delete" size="sm" :aria-label="t('common.delete')" @click="confirmDelete(row)">
            <q-tooltip>{{ t('common.delete') }}</q-tooltip>
          </q-btn>
        </q-td>
      </template>

      <template #item="{ row }">
        <div class="col-12 col-sm-6 q-pa-xs">
          <q-card flat bordered class="llm-grid-card full-height">
            <q-card-section class="q-pb-sm">
              <div class="llm-grid-card__header">
                <q-icon
                  :name="availability.has(row.id)
                    ? (availability.get(row.id) ? 'check_circle' : 'error')
                    : 'help'"
                  :color="availability.has(row.id)
                    ? (availability.get(row.id) ? 'positive' : 'negative')
                    : 'grey-6'"
                  size="sm"
                  class="q-mt-xs"
                />
                <div class="col llm-grid-card__copy">
                  <div class="text-subtitle1 text-weight-bold">{{ row.label }}</div>
                  <div class="text-caption text-grey-7 llm-grid-card__model">{{ row.llm_name }}</div>
                </div>
                <div v-if="canEdit" class="llm-grid-card__actions row justify-end">
                  <q-btn
                    flat
                    round
                    color="secondary"
                    icon="fact_check"
                    size="sm"
                    :loading="checkingLlmId === row.id"
                    :disable="checkingAll || checkingLlmId !== null"
                    :aria-label="t('llm.checkOne')"
                    @click="checkOneLlm(row)"
                  >
                    <q-tooltip>{{ t('llm.checkOne') }}</q-tooltip>
                  </q-btn>
                  <q-btn flat round color="primary" icon="edit" size="sm" :aria-label="t('common.edit')" @click="openEdit(row)" />
                  <q-btn flat round color="negative" icon="delete" size="sm" :aria-label="t('common.delete')" @click="confirmDelete(row)" />
                </div>
              </div>
            </q-card-section>

            <q-separator />

            <q-card-section class="q-py-sm">
              <div class="llm-badges row q-mb-sm">
                <q-badge color="secondary" outline>{{ row.provider_name }}</q-badge>
                <q-badge
                  v-for="capability in configuredCapabilities(row)"
                  :key="capability"
                  :style="{ color: solaireCss.blue.accent }"
                  outline
                >
                  {{ capabilityMeta(capability).label }}
                </q-badge>
              </div>
              <div class="text-caption text-grey-7">{{ t('llm.colCode') }}</div>
              <div class="llm-grid-card__code">{{ row.code }}</div>
              <div v-if="hasContext(row.context_length)" class="text-caption text-grey-7 q-mt-sm">
                {{ formatContext(row.context_length) }}
              </div>
              <div class="llm-badges row q-mt-xs">
                <q-badge v-if="row.is_subscription" color="green" outline>
                  {{ t('llm.subscriptionBadge') }}
                </q-badge>
                <q-badge v-if="hasPrice(row.cost_per_input_token)" color="primary" outline>
                  {{ t('llm.costInShort') }} {{ formatPrice(row.cost_per_input_token) }}
                </q-badge>
                <q-badge v-if="hasPrice(row.cost_per_cached_input_token)" color="indigo" outline>
                  {{ t('llm.costCacheShort') }} {{ formatPrice(row.cost_per_cached_input_token) }}
                </q-badge>
                <q-badge v-if="hasPrice(row.cost_per_output_token)" color="teal" outline>
                  {{ t('llm.costOutShort') }} {{ formatPrice(row.cost_per_output_token) }}
                </q-badge>
              </div>
            </q-card-section>
          </q-card>
        </div>
      </template>

      <template #no-data>
        <div class="full-width column flex-center text-grey-6 q-pa-xl">
          <q-icon name="smart_toy" size="42px" class="q-mb-sm" />
          <div>{{ t('llm.noLlm') }}</div>
        </div>
      </template>
    </q-table>

    <q-dialog v-model="dialogOpen">
      <q-card class="llm-dialog column no-wrap">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="llm-dialog__heading">
            <div class="text-h6">{{ editing ? t('llm.editLlm') : t('llm.addLlm') }}</div>
            <div class="text-caption text-grey-7">{{ t('llm.llmDialogHint') }}</div>
          </div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="$t('common.close')" />
        </q-card-section>
        <q-separator />

        <q-form class="llm-dialog__form column no-wrap col" @submit="saveLlm">
          <q-card-section class="llm-dialog__body scroll">
            <div class="llm-form-grid">
              <div class="llm-form-field llm-form-field--provider">
                <div class="llm-form-field__label">{{ t('llm.colProvider') }} *</div>
                <q-select
                  v-model="form.llm_provider_id"
                  :options="providerOptions"
                  option-value="value"
                  option-label="label"
                  emit-value
                  map-options
                  outlined
                  hide-bottom-space
                  :aria-label="t('llm.colProvider')"
                  :loading="initializing"
                  :disable="initializing"
                  :rules="[value => Boolean(value) || t('llm.providerRequired')]"
                  @update:model-value="onProviderChange"
                />
              </div>

              <div class="llm-form-field llm-form-field--capability">
                <div class="llm-form-field__label">{{ t('llm.resourceCapability') }} *</div>
                <q-select
                  v-model="form.primary_capability"
                  :options="capabilityOptions"
                  emit-value
                  map-options
                  outlined
                  hide-bottom-space
                  @update:model-value="reloadSelectedProviderModels"
                />
              </div>

              <div class="llm-form-field llm-form-field--full">
                <div class="llm-form-field__label">{{ t('llm.colModel') }} *</div>
                <q-select
                  v-model="form.llm_name"
                  :options="filteredModels"
                  option-value="id"
                  option-label="name"
                  emit-value
                  map-options
                  use-input
                  fill-input
                  hide-selected
                  new-value-mode="add-unique"
                  input-debounce="200"
                  outlined
                  hide-bottom-space
                  :aria-label="t('llm.colModel')"
                  :loading="loadingModels"
                  :disable="!form.llm_provider_id || loadingModels"
                  :rules="[value => Boolean(value) || t('llm.modelRequired')]"
                  @filter="filterModels"
                  @update:model-value="onModelSelected"
                >
                  <template #option="scope">
                    <q-item v-bind="scope.itemProps">
                      <q-item-section>
                        <q-item-label>{{ scope.opt.name || scope.opt.id }}</q-item-label>
                        <q-item-label v-if="scope.opt.name && scope.opt.name !== scope.opt.id" caption>
                          {{ scope.opt.id }}
                        </q-item-label>
                      </q-item-section>
                      <q-item-section side>
                        <div class="row q-gutter-xs">
                          <q-badge v-if="scope.opt.context_length" color="blue-grey" outline>
                            {{ compactNumber(scope.opt.context_length) }}
                          </q-badge>
                          <q-badge v-if="scope.opt.capabilities?.tools" color="primary" outline>Tools</q-badge>
                          <q-badge v-if="scope.opt.capabilities?.reasoning" color="deep-purple" outline>R</q-badge>
                        </div>
                      </q-item-section>
                    </q-item>
                  </template>
                  <template #no-option>
                    <q-item>
                      <q-item-section class="text-grey-7">
                        {{ modelsLoadError || t('llm.exactModelName') }}
                      </q-item-section>
                    </q-item>
                  </template>
                </q-select>
                <q-banner
                  v-if="modelsLoadError"
                  dense
                  rounded
                  class="bg-red-1 text-negative q-mt-sm"
                >
                  {{ modelsLoadError }}
                  <template #action>
                    <q-btn
                      flat
                      color="negative"
                      icon="refresh"
                      :label="t('common.retry')"
                      :loading="loadingModels"
                      @click="reloadSelectedProviderModels"
                    />
                  </template>
                </q-banner>
                <div class="llm-form-field__help">{{ t('llm.modelHint') }}</div>
              </div>

              <div class="llm-form-field llm-form-field--code">
                <div class="llm-form-field__label">{{ t('llm.code') }}</div>
                <q-input
                  v-model="form.code"
                  outlined
                  hide-bottom-space
                  :aria-label="t('llm.code')"
                  :rules="[
                    value => Boolean(value) || t('llm.codeRequired'),
                    value => /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$/.test(value) || t('llm.codeInvalid'),
                  ]"
                />
                <div class="llm-form-field__help">{{ t('llm.codeHint') }}</div>
              </div>

              <div class="llm-form-field llm-form-field--label">
                <div class="llm-form-field__label">{{ t('llm.customLabel') }}</div>
                <q-input
                  v-model="form.label"
                  outlined
                  hide-bottom-space
                  :aria-label="t('llm.customLabel')"
                  :rules="[value => Boolean(value) || t('llm.labelRequired')]"
                />
                <div class="llm-form-field__help">{{ t('llm.customLabelHint') }}</div>
              </div>

              <div class="llm-form-field llm-form-field--full">
                <div class="llm-form-field__label">{{ t('llm.contextLength') }}</div>
                <q-input
                  v-model.number="form.context_length"
                  type="number"
                  min="1"
                  step="1"
                  clearable
                  outlined
                  hide-bottom-space
                  :aria-label="t('llm.contextLength')"
                />
                <div class="llm-form-field__help">{{ t('llm.contextLengthHint') }}</div>
              </div>

              <div class="llm-form-field llm-form-field--full">
                <q-toggle
                  v-model="form.is_subscription"
                  color="positive"
                  :label="t('llm.subscription')"
                />
                <div class="llm-form-field__help">{{ t('llm.subscriptionHint') }}</div>
              </div>

              <div v-if="showTokenPricing" class="llm-form-field llm-form-field--cost">
                <div class="llm-form-field__label">{{ t('llm.inputCost') }}</div>
                <q-input
                  v-model.number="form.cost_per_input_token"
                  type="number"
                  min="0"
                  step="0.000001"
                  clearable
                  outlined
                  hide-bottom-space
                  :aria-label="t('llm.inputCost')"
                />
                <div class="llm-form-field__help">{{ t('llm.inputCostHint') }}</div>
              </div>

              <div v-if="showTokenPricing" class="llm-form-field llm-form-field--cost">
                <div class="llm-form-field__label">{{ t('llm.cachedInputCost') }}</div>
                <q-input
                  v-model.number="form.cost_per_cached_input_token"
                  type="number"
                  min="0"
                  step="0.000001"
                  clearable
                  outlined
                  hide-bottom-space
                  :aria-label="t('llm.cachedInputCost')"
                />
                <div class="llm-form-field__help">{{ t('llm.cachedInputCostHint') }}</div>
              </div>

              <div v-if="showTokenPricing" class="llm-form-field llm-form-field--cost">
                <div class="llm-form-field__label">{{ t('llm.outputCost') }}</div>
                <q-input
                  v-model.number="form.cost_per_output_token"
                  type="number"
                  min="0"
                  step="0.000001"
                  clearable
                  outlined
                  hide-bottom-space
                  :aria-label="t('llm.outputCost')"
                />
                <div class="llm-form-field__help">{{ t('llm.outputCostHint') }}</div>
              </div>

              <div class="llm-modalities llm-form-field--full">
                <div class="text-subtitle2">{{ t('llm.detectedCapabilities') }}</div>
                <div class="llm-form-field__help q-mb-md">{{ t('llm.detectedCapabilitiesHelp') }}</div>
                <div class="row q-gutter-xs">
                  <q-chip
                    v-for="capability in form.service_capabilities"
                    :key="capability"
                    dense
                    square
                    outline
                    :icon="capabilityMeta(capability).icon"
                    :color="capabilityMeta(capability).color"
                  >
                    {{ capabilityMeta(capability).label }}
                  </q-chip>
                  <q-chip
                    v-for="badge in formModalityBadges"
                    :key="badge.key"
                    dense
                    square
                    outline
                    :color="badge.color"
                  >
                    {{ badge.label }}
                  </q-chip>
                </div>
                <LlmCapabilityRefresh
                  v-if="editing && dialogOpen && canEdit && form.llm_provider_id"
                  :provider-id="form.llm_provider_id"
                  :model-name="form.llm_name"
                  :capability="form.primary_capability"
                  :modalities="modalitiesPayload()"
                  :service-capabilities="form.service_capabilities"
                  @apply="applyRefreshedCapabilities"
                />
              </div>
            </div>
          </q-card-section>

          <q-separator />
          <q-card-actions align="right" class="llm-dialog__actions q-pa-md galaris-dialog-actions">
            <q-btn v-close-popup flat :label="t('common.cancel')" />
            <q-btn
              v-if="canEdit"
              type="submit"
              color="primary"
              icon="save"
              :label="t('common.save')"
              :loading="store.loading"
              :disable="!form.llm_provider_id || !form.llm_name || !form.code || !form.label"
            />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>

    <q-dialog v-model="deleteDialog">
      <q-card style="width: 480px; max-width: 92vw">
        <q-card-section class="galaris-dialog-title">
          <div class="text-h6">{{ t('common.confirm') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="$t('common.close')" />
        </q-card-section>
        <q-card-section>{{ t('llm.confirmDeleteLlm', { name: llmToDelete?.label }) }}</q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn v-if="canEdit" color="negative" :label="t('common.delete')" :loading="store.loading" @click="deleteLlm" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { solaireCss } from '@/core/util'
import { useLLMProviderStore } from '../stores/llmProviderStore'
import LlmCapabilityRefresh from './LlmCapabilityRefresh.vue'
import type {
  LLMModalities,
  LLMModelInfo,
  LLMWithProvider,
  AICapability,
  AIResourceType,
} from '../services/llmProviderService'

const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.LLM_PROVIDER_EDIT))

type LlmForm = LLMModalities & {
  id: number | null
  llm_provider_id: number | null
  code: string
  llm_name: string
  label: string
  context_length: number | null
  cost_per_input_token: number | null
  cost_per_cached_input_token: number | null
  cost_per_output_token: number | null
  is_subscription: boolean
  resource_type: AIResourceType
  primary_capability: AICapability
  service_capabilities: AICapability[]
  pricing: Record<string, unknown>
}

const { showHeading = true } = defineProps<{
  showHeading?: boolean
}>()

const store = useLLMProviderStore()
const $q = useQuasar()
const { t, locale } = useI18n()
const dialogOpen = ref(false)
const deleteDialog = ref(false)
const editing = ref(false)
const checkingAll = ref(false)
const checkingLlmId = ref<number | null>(null)
const initializing = ref(false)
const loadingModels = ref(false)
const availableModels = ref<LLMModelInfo[]>([])
const filteredModels = ref<LLMModelInfo[]>([])
const searchNeedle = ref('')
const modelsLoadError = ref<string | null>(null)
const selectedProviderName = ref('')
const availability = ref(new Map<number, boolean>())
const llmToDelete = ref<LLMWithProvider | null>(null)
let initialized = false
let initializationPromise: Promise<void> | null = null
let modelLoadGeneration = 0

const form = reactive<LlmForm>(emptyForm())

const providerOptions = computed(() => {
  const active = store.activeProviders
  const selected = form.llm_provider_id
    ? store.providers.find(provider => provider.id === form.llm_provider_id)
    : undefined
  const providers = selected && !active.some(provider => provider.id === selected.id)
    ? [...active, selected]
    : active
  const options = providers.map(provider => ({
    value: provider.id,
    label: provider.name,
  }))
  if (
    form.llm_provider_id
    && !options.some(option => option.value === form.llm_provider_id)
    && selectedProviderName.value
  ) {
    options.push({
      value: form.llm_provider_id,
      label: selectedProviderName.value,
    })
  }
  return options
})

const selectedCatalogItem = computed(() => store.catalogItems.find(
  item => item.connection?.id === form.llm_provider_id,
))
const capabilityOptions = computed(() => {
  const values = selectedCatalogItem.value?.capabilities || [form.primary_capability, 'chat']
  return [...new Set(values)].map(value => ({
    value,
    label: capabilityMeta(value).label,
    icon: capabilityMeta(value).icon,
  }))
})
const showTokenPricing = computed(() => (
  ['chat', 'vision', 'embedding'] as AICapability[]
).includes(form.primary_capability))

const formModalityBadges = computed(() => {
  const result: { key: string; label: string; color: string }[] = []
  for (const direction of ['input', 'output'] as const) {
    for (const name of ['text', 'image', 'file', 'video', 'audio'] as const) {
      const key = `${direction}_${name}` as keyof LLMModalities
      if (!form[key]) continue
      result.push({
        key,
        label: `${direction === 'input' ? t('llm.input') : t('llm.output')} · ${t(`llm.${name}`)}`,
        color: direction === 'input' ? 'primary' : 'teal',
      })
    }
  }
  return result
})

const llmsWithProviderNames = computed(() => store.llms.map(llm => ({
  ...llm,
  provider_name: llm.provider_name
    || store.providers.find(provider => provider.id === llm.llm_provider_id)?.name
    || t('llm.fallbackUnknown'),
})))

function configuredCapabilities(llm: LLMWithProvider): AICapability[] {
  return [...new Set([llm.primary_capability, ...llm.service_capabilities])]
}

const columns = computed(() => [
  { name: 'status', label: t('llm.colStatus'), field: 'status', align: 'center' as const, headerStyle: 'width: 64px' },
  { name: 'code', label: t('llm.colCode'), field: 'code', sortable: true, align: 'left' as const },
  { name: 'label', label: t('llm.colLabel'), field: 'label', sortable: true, align: 'left' as const },
  { name: 'primary_capability', label: t('llm.resourceCapability'), field: 'primary_capability', sortable: true, align: 'left' as const },
  { name: 'llm_name', label: t('llm.colModel'), field: 'llm_name', sortable: true, align: 'left' as const },
  { name: 'provider_name', label: t('llm.colProvider'), field: 'provider_name', sortable: true, align: 'left' as const },
  { name: 'llm_metrics', label: t('llm.colMetrics'), field: 'llm_metrics', align: 'left' as const },
  { name: 'actions', label: t('common.actions'), field: 'actions', align: 'right' as const, headerStyle: 'width: 112px' },
])

function emptyForm(): LlmForm {
  return {
    id: null,
    llm_provider_id: null,
    code: '',
    llm_name: '',
    label: '',
    context_length: null,
    cost_per_input_token: null,
    cost_per_cached_input_token: null,
    cost_per_output_token: null,
    is_subscription: false,
    resource_type: 'model',
    primary_capability: 'chat',
    service_capabilities: ['chat'],
    pricing: {},
    input_text: true,
    input_image: false,
    input_file: false,
    input_video: false,
    input_audio: false,
    output_text: true,
    output_image: false,
    output_file: false,
    output_video: false,
    output_audio: false,
  }
}

function resetForm(): void {
  modelLoadGeneration += 1
  Object.assign(form, emptyForm())
  availableModels.value = []
  filteredModels.value = []
  searchNeedle.value = ''
  modelsLoadError.value = null
  selectedProviderName.value = ''
}

async function ensureInitialized(): Promise<void> {
  if (initialized) return
  if (initializationPromise) return initializationPromise
  initializing.value = true
  initializationPromise = Promise.all([
    store.fetchProviders(),
    store.fetchCatalog(),
    store.fetchLLMs(),
  ]).then(() => {
    initialized = true
  }).finally(() => {
    initializing.value = false
    initializationPromise = null
  })
  return initializationPromise
}

function notifyInitializationError(error: unknown): void {
  $q.notify({
    type: 'negative',
    message: errorMessage(error) || t('llm.notify.fetchProvidersError'),
  })
}

async function openCreate(): Promise<void> {
  if (!canEdit.value) return
  try {
    await ensureInitialized()
  } catch (error) {
    notifyInitializationError(error)
  }
  resetForm()
  editing.value = false
  dialogOpen.value = true
}

async function openForModel(providerId: number, model: LLMModelInfo): Promise<void> {
  try {
    await ensureInitialized()
  } catch (error) {
    notifyInitializationError(error)
  }
  resetForm()
  editing.value = false
  form.llm_provider_id = providerId
  selectedProviderName.value = store.providers.find(provider => provider.id === providerId)?.name || ''
  form.primary_capability = model.service_capabilities[0] || 'chat'
  availableModels.value = [model]
  filteredModels.value = [model]
  applyModel(model)
  dialogOpen.value = true
  await loadModels(providerId)
  const refreshed = availableModels.value.find(item => item.id === model.id)
  if (refreshed) applyModel(refreshed)
}

async function openEdit(llm: LLMWithProvider): Promise<void> {
  if (!canEdit.value) return
  resetForm()
  editing.value = true
  selectedProviderName.value = llm.provider_name
  Object.assign(form, {
    id: llm.id,
    llm_provider_id: llm.llm_provider_id,
    code: llm.code,
    llm_name: llm.llm_name,
    label: llm.label,
    context_length: llm.context_length ?? null,
    cost_per_input_token: llm.cost_per_input_token ?? null,
    cost_per_cached_input_token: llm.cost_per_cached_input_token ?? null,
    cost_per_output_token: llm.cost_per_output_token ?? null,
    is_subscription: llm.is_subscription,
    resource_type: llm.resource_type,
    primary_capability: llm.primary_capability,
    service_capabilities: [...llm.service_capabilities],
    pricing: { ...llm.pricing },
    input_text: llm.input_text,
    input_image: llm.input_image,
    input_file: llm.input_file,
    input_video: llm.input_video,
    input_audio: llm.input_audio,
    output_text: llm.output_text,
    output_image: llm.output_image,
    output_file: llm.output_file,
    output_video: llm.output_video,
    output_audio: llm.output_audio,
  })
  dialogOpen.value = true
  try {
    await ensureInitialized()
  } catch (error) {
    notifyInitializationError(error)
  }
  await loadModels(llm.llm_provider_id)
}

async function loadModels(providerId: number): Promise<void> {
  const generation = ++modelLoadGeneration
  const capability = form.primary_capability
  loadingModels.value = true
  modelsLoadError.value = null
  try {
    const response = await store.fetchProviderResources(providerId, capability)
    if (
      generation !== modelLoadGeneration
      || form.llm_provider_id !== providerId
      || form.primary_capability !== capability
    ) return
    availableModels.value = withSelectedModel(response.models)
    recomputeFilteredModels()
  } catch (error) {
    if (generation !== modelLoadGeneration) return
    availableModels.value = withSelectedModel([])
    recomputeFilteredModels()
    modelsLoadError.value = errorMessage(error) || t('llm.notify.loadModelsError')
    $q.notify({
      type: 'negative',
      message: modelsLoadError.value,
    })
  } finally {
    if (generation === modelLoadGeneration) loadingModels.value = false
  }
}

async function onProviderChange(providerId: number | null): Promise<void> {
  selectedProviderName.value = providerId
    ? store.providers.find(provider => provider.id === providerId)?.name || ''
    : ''
  const item = store.catalogItems.find(entry => entry.connection?.id === providerId)
  if (item && !item.capabilities.includes(form.primary_capability)) {
    form.primary_capability = item.capabilities[0] || 'chat'
  }
  resetSelectedModel()
  modelsLoadError.value = null
  if (providerId) await loadModels(providerId)
  else {
    availableModels.value = []
    filteredModels.value = []
  }
}

async function reloadSelectedProviderModels(): Promise<void> {
  resetSelectedModel()
  if (form.llm_provider_id) await loadModels(form.llm_provider_id)
}

function filterModels(value: string, update: (callback: () => void) => void): void {
  update(() => {
    searchNeedle.value = value.trim().toLowerCase()
    recomputeFilteredModels()
  })
}

function recomputeFilteredModels(): void {
  const needle = searchNeedle.value
  filteredModels.value = !needle
    ? availableModels.value
    : availableModels.value.filter(model =>
      model.id.toLowerCase().includes(needle)
      || model.name?.toLowerCase().includes(needle)
      || model.description?.toLowerCase().includes(needle),
    )
}

function onModelSelected(modelId: string | null): void {
  if (!modelId) return
  const model = availableModels.value.find(item => item.id === modelId)
  if (model) {
    applyModel(model)
    return
  }
  form.llm_name = modelId.trim()
  resetModelMetadata()
  if (!editing.value) {
    form.label = form.llm_name
    form.code = uniqueCode(form.llm_name)
  }
  availableModels.value = withSelectedModel(availableModels.value)
  recomputeFilteredModels()
}

function withSelectedModel(models: LLMModelInfo[]): LLMModelInfo[] {
  const unique = [...new Map(models.filter(model => model.id).map(model => [model.id, model])).values()]
  if (!form.llm_name || unique.some(model => model.id === form.llm_name)) return unique
  return [{
    id: form.llm_name,
    name: form.llm_name,
    description: null,
    context_length: form.context_length,
    pricing: { ...form.pricing },
    modalities: modalitiesPayload(),
    capabilities: null,
    resource_type: form.resource_type,
    service_capabilities: [...form.service_capabilities],
  }, ...unique]
}

function applyModel(model: LLMModelInfo): void {
  form.llm_name = model.id
  form.context_length = model.context_length ?? null
  form.cost_per_input_token = price(model, 'input')
  form.cost_per_cached_input_token = price(model, 'cached_input')
  form.cost_per_output_token = price(model, 'output')
  form.resource_type = model.resource_type
  form.service_capabilities = model.service_capabilities.length
    ? [...new Set([form.primary_capability, ...model.service_capabilities])]
    : [form.primary_capability]
  form.pricing = { ...(model.pricing || {}) }
  Object.assign(
    form,
    defaultModalities(form.primary_capability),
    model.modalities || {},
  )
  if (!editing.value) {
    form.label = model.name || model.id
    form.code = uniqueCode(model.id)
  }
}

function resetSelectedModel(): void {
  form.llm_name = ''
  if (!editing.value) {
    form.code = ''
    form.label = ''
  }
  resetModelMetadata()
}

function resetModelMetadata(): void {
  form.context_length = null
  form.cost_per_input_token = null
  form.cost_per_cached_input_token = null
  form.cost_per_output_token = null
  form.resource_type = 'model'
  form.service_capabilities = [form.primary_capability]
  form.pricing = {}
  Object.assign(form, defaultModalities(form.primary_capability))
}

function price(model: LLMModelInfo, key: string): number | null {
  const value = model.pricing?.[key]
  if (value === null || value === undefined || value === '') return null
  const amount = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(amount) ? amount : null
}

function capabilityMeta(capability: AICapability): { label: string; icon: string; color: string } {
  const values: Record<AICapability, { label: string; icon: string; color: string }> = {
    chat: { label: t('llm.capabilities.chat'), icon: 'chat', color: 'primary' },
    vision: { label: t('llm.capabilities.vision'), icon: 'visibility', color: 'blue' },
    image_generation: { label: t('llm.capabilities.image_generation'), icon: 'image', color: 'pink' },
    embedding: { label: t('llm.capabilities.embedding'), icon: 'scatter_plot', color: 'indigo' },
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

function defaultModalities(capability: AICapability): LLMModalities {
  const values: LLMModalities = {
    input_text: false,
    input_image: false,
    input_file: false,
    input_video: false,
    input_audio: false,
    output_text: false,
    output_image: false,
    output_file: false,
    output_video: false,
    output_audio: false,
  }
  if (capability === 'chat') Object.assign(values, { input_text: true, output_text: true })
  if (capability === 'vision') Object.assign(values, { input_text: true, input_image: true, output_text: true })
  if (capability === 'image_generation') Object.assign(values, { input_text: true, output_image: true })
  if (capability === 'embedding') values.input_text = true
  if (capability === 'transcription') Object.assign(values, { input_audio: true, output_text: true })
  if (capability === 'speech') Object.assign(values, { input_text: true, output_audio: true })
  if (capability === 'realtime_conversation') Object.assign(values, {
    input_text: true,
    input_audio: true,
    output_text: true,
    output_audio: true,
  })
  if (capability === 'audio_understanding') Object.assign(values, { input_text: true, input_audio: true, output_text: true })
  if (capability === 'video_understanding') Object.assign(values, { input_text: true, input_video: true, output_text: true })
  if (capability === 'sound_generation' || capability === 'music_generation') Object.assign(values, { input_text: true, output_audio: true })
  if (capability === 'video_generation') Object.assign(values, { input_text: true, output_video: true })
  return values
}

function uniqueCode(modelId: string): string {
  const normalized = modelId
    .toLowerCase()
    .replace(/[^a-z0-9_.-]+/g, '-')
    .replace(/^[^a-z0-9]+|[^a-z0-9]+$/g, '')
    .slice(0, 90) || 'model'
  const existing = new Set(store.llms.filter(llm => llm.id !== form.id).map(llm => llm.code))
  if (!existing.has(normalized)) return normalized
  let suffix = 2
  while (existing.has(`${normalized.slice(0, 95)}-${suffix}`)) suffix += 1
  return `${normalized.slice(0, 95)}-${suffix}`
}

function applyRefreshedCapabilities(modalities: Partial<LLMModalities>, capabilities: AICapability[]) {
  if (!canEdit.value) return
  Object.assign(form, modalities)
  form.service_capabilities = capabilities
}

function modalitiesPayload(): LLMModalities {
  return {
    input_text: form.input_text,
    input_image: form.input_image,
    input_file: form.input_file,
    input_video: form.input_video,
    input_audio: form.input_audio,
    output_text: form.output_text,
    output_image: form.output_image,
    output_file: form.output_file,
    output_video: form.output_video,
    output_audio: form.output_audio,
  }
}

async function saveLlm(): Promise<void> {
  if (!canEdit.value) return
  if (!form.llm_provider_id) return
  const payload = {
    llm_provider_id: form.llm_provider_id,
    code: form.code,
    llm_name: form.llm_name,
    label: form.label,
    context_length: form.context_length,
    cost_per_input_token: form.cost_per_input_token,
    cost_per_cached_input_token: form.cost_per_cached_input_token,
    cost_per_output_token: form.cost_per_output_token,
    is_subscription: form.is_subscription,
    resource_type: form.resource_type,
    primary_capability: form.primary_capability,
    service_capabilities: form.service_capabilities,
    pricing: form.pricing,
    ...modalitiesPayload(),
  }
  try {
    if (editing.value && form.id) {
      await store.updateLLM(form.id, payload)
      $q.notify({ type: 'positive', message: t('llm.notify.llmUpdated') })
    } else {
      await store.createLLM(payload)
      $q.notify({ type: 'positive', message: t('llm.notify.llmAdded') })
    }
    dialogOpen.value = false
  } catch (error) {
    $q.notify({ type: 'negative', message: errorMessage(error) || t('llm.notify.llmSaveError') })
  }
}

function confirmDelete(llm: LLMWithProvider): void {
  if (!canEdit.value) return
  llmToDelete.value = llm
  deleteDialog.value = true
}

async function deleteLlm(): Promise<void> {
  if (!canEdit.value) return
  if (!llmToDelete.value) return
  try {
    await store.deleteLLM(llmToDelete.value.id)
    availability.value.delete(llmToDelete.value.id)
    deleteDialog.value = false
    $q.notify({ type: 'positive', message: t('llm.notify.llmDeleted') })
  } catch (error) {
    $q.notify({ type: 'negative', message: errorMessage(error) || t('llm.notify.llmDeleteError') })
  }
}

async function checkAllLlms(): Promise<void> {
  if (!canEdit.value) return
  checkingAll.value = true
  availability.value = new Map()
  try {
    const results = await store.checkAllLLMs()
    availability.value = results
    const availableCount = [...results.values()].filter(Boolean).length
    const unavailableCount = results.size - availableCount
    $q.notify({
      type: unavailableCount ? 'warning' : 'positive',
      message: unavailableCount
        ? t('llm.notify.unavailableSummary', { unavailable: unavailableCount, total: results.size })
        : t('llm.notify.allAvailable', { total: results.size }),
    })
  } catch (error) {
    $q.notify({ type: 'negative', message: t('llm.notify.checkError') })
  } finally {
    checkingAll.value = false
  }
}

async function checkOneLlm(llm: LLMWithProvider): Promise<void> {
  if (!canEdit.value || checkingAll.value || checkingLlmId.value !== null) return
  checkingLlmId.value = llm.id
  const pendingAvailability = new Map(availability.value)
  pendingAvailability.delete(llm.id)
  availability.value = pendingAvailability
  try {
    const isAvailable = await store.checkLLMAvailability(llm)
    const nextAvailability = new Map(availability.value)
    nextAvailability.set(llm.id, isAvailable)
    availability.value = nextAvailability
    $q.notify({
      type: isAvailable ? 'positive' : 'warning',
      message: t(isAvailable ? 'llm.notify.llmAvailable' : 'llm.notify.llmUnavailable', {
        name: llm.label,
      }),
    })
  } catch (error) {
    const nextAvailability = new Map(availability.value)
    nextAvailability.set(llm.id, false)
    availability.value = nextAvailability
    $q.notify({
      type: 'negative',
      message: errorMessage(error) || t('llm.notify.checkError'),
    })
  } finally {
    checkingLlmId.value = null
  }
}

onMounted(() => {
  void ensureInitialized().catch(notifyInitializationError)
})

function hasPrice(value: unknown): boolean {
  return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
}

function formatPrice(value: unknown): string {
  return new Intl.NumberFormat(locale.value, {
    style: 'currency',
    currency: 'USD',
    currencyDisplay: 'narrowSymbol',
    maximumFractionDigits: 6,
  }).format(Number(value))
}

function hasContext(value: unknown): boolean {
  return Number.isFinite(Number(value)) && Number(value) > 0
}

function formatContext(value: unknown): string {
  return `${Number(value).toLocaleString(locale.value)} tokens`
}

function compactNumber(value: number): string {
  return new Intl.NumberFormat(locale.value, { notation: 'compact' }).format(value)
}

function errorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null) {
    const response = (error as { response?: { data?: { detail?: unknown } } }).response
    const detail = response?.data?.detail
    if (typeof detail === 'string') return detail
    if (typeof detail === 'object' && detail !== null && 'message' in detail) {
      return String((detail as { message: unknown }).message)
    }
  }
  return error instanceof Error ? error.message : ''
}

defineExpose({ openCreate, openForModel })
</script>

<style scoped>
.configured-llm-manager {
  min-width: 0;
}

.configured-llm-toolbar,
.llm-toolbar-actions {
  gap: 8px;
}

.configured-llm-table :deep(table) {
  width: 100%;
  table-layout: fixed;
}

.configured-llm-table :deep(th),
.configured-llm-table :deep(td) {
  padding: 8px;
  white-space: normal;
  overflow-wrap: anywhere;
}

.configured-llm-table :deep(.q-badge) {
  max-width: 100%;
  white-space: normal;
  overflow-wrap: anywhere;
}

.llm-badges {
  gap: 4px;
}

.llm-grid-card__header {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 8px;
}

.llm-grid-card__actions {
  grid-column: 1 / -1;
}

.llm-grid-card__copy {
  min-width: 0;
  overflow-wrap: anywhere;
}

.llm-grid-card__model,
.llm-grid-card__code {
  overflow-wrap: anywhere;
}

.llm-dialog {
  width: 920px;
  max-width: 96vw;
  max-height: 92vh;
}

.llm-dialog__heading,
.llm-dialog__form,
.llm-form-field,
.llm-modalities {
  min-width: 0;
}

.llm-dialog__body {
  flex: 1 1 auto;
  min-height: 0;
  padding: 24px;
}

.llm-dialog__form {
  overflow: hidden;
}

.llm-form-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 24px 20px;
  align-items: start;
}

.llm-form-field--provider {
  grid-column: span 8;
}

.llm-form-field--capability {
  grid-column: span 4;
}

.llm-form-field--full,
.llm-modalities {
  grid-column: 1 / -1;
}

.llm-form-field--code {
  grid-column: span 5;
}

.llm-form-field--label {
  grid-column: span 7;
}

.llm-form-field--cost {
  grid-column: span 4;
}

.llm-form-field__label {
  margin-bottom: 7px;
  color: #303030;
  font-size: 0.875rem;
  font-weight: 600;
  line-height: 1.35;
}

.llm-form-field--cost .llm-form-field__label {
  display: flex;
  align-items: flex-end;
  min-height: 2.7em;
}

.llm-form-field__help {
  margin-top: 6px;
  color: #616161;
  font-size: 0.75rem;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.llm-modalities {
  padding: 16px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  background: #fafafa;
}

.llm-modalities__columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.llm-modalities__group {
  min-width: 0;
  padding: 14px;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  background: white;
}

.llm-modalities__options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 12px;
}

.llm-modalities__options :deep(.q-toggle__label) {
  overflow-wrap: anywhere;
}

.llm-dialog__actions {
  flex: 0 0 auto;
  background: white;
}

body.body--dark .llm-form-field__label {
  color: #e0e0e0;
}

body.body--dark .llm-form-field__help {
  color: #9e9e9e;
}

body.body--dark .llm-modalities {
  border-color: #3a3f47;
  background: #232323;
}

body.body--dark .llm-modalities__group {
  border-color: #3a3f47;
  background: #1d1d1d;
}

body.body--dark .llm-dialog__actions {
  background: #1d1d1d;
}

@media (max-width: 700px) {
  .configured-llm-toolbar,
  .llm-toolbar-actions {
    width: 100%;
  }

  .llm-toolbar-actions > :deep(.q-btn) {
    flex: 1 1 140px;
  }

  .llm-dialog {
    max-width: 100vw;
    max-height: 96vh;
  }

  .llm-dialog__body {
    padding: 16px;
  }

  .llm-form-grid {
    gap: 20px;
  }

  .llm-form-field--provider,
  .llm-form-field--capability,
  .llm-form-field--code,
  .llm-form-field--label,
  .llm-form-field--cost {
    grid-column: 1 / -1;
  }

  .llm-form-field--cost .llm-form-field__label {
    min-height: 0;
  }

  .llm-modalities__columns,
  .llm-modalities__options {
    grid-template-columns: 1fr;
  }

  .llm-dialog__actions :deep(.q-btn) {
    flex: 1 1 auto;
  }
}
</style>
