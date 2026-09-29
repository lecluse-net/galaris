<template>
  <section class="provider-config-panel column no-wrap">
    <template v-if="item">
      <div class="provider-panel-header q-pa-md">
        <div class="row items-start no-wrap q-gutter-md">
          <ProviderAvatar :item="item" size="44px" />
          <div class="col">
            <div class="row items-center q-gutter-sm">
              <div class="text-h6 text-weight-bold">{{ item.display_name }}</div>
              <q-badge :color="draft.is_active ? 'positive' : 'grey-7'" outline>
                {{ draft.is_active ? t('llm.active') : t('llm.inactive') }}
              </q-badge>
            </div>
          </div>
        </div>
      </div>

      <component
        :is="$q.screen.width < 1280 ? 'div' : QScrollArea"
        v-bind="$q.screen.width < 1280 ? {} : { visible: true, thumbStyle: { width: '8px', backgroundColor: 'var(--q-primary)', opacity: '0.65' } }"
        class="col provider-config-scroll"
      >
        <q-form ref="providerForm" class="q-pa-md q-gutter-md" @submit.prevent="submit">
          <q-banner rounded class="provider-guide bg-blue-1 text-blue-10">
            <template #avatar><q-icon name="route" color="primary" /></template>
            {{ guideText }}
          </q-banner>

          <q-banner
            v-if="isChatGptSubscription"
            rounded
            class="bg-amber-1 text-amber-10"
          >
            <template #avatar><q-icon name="policy" color="amber-9" /></template>
            <div class="text-weight-bold">{{ t('llm.chatGptPolicyTitle') }}</div>
            <div>{{ t('llm.chatGptPolicyBody') }}</div>
            <div class="q-mt-sm">{{ t('llm.chatGptPolicyThirdParties') }}</div>
            <div class="q-mt-sm text-caption">{{ t('llm.chatGptResponsibility') }}</div>
            <div class="q-mt-xs text-caption">
              <a
                href="https://openai.com/policies/terms-of-use/"
                target="_blank"
                rel="noopener noreferrer"
                class="text-primary"
              >
                {{ t('llm.chatGptTermsLink') }}
                <q-icon name="open_in_new" size="14px" />
              </a>
            </div>
          </q-banner>

          <div class="row items-center justify-between rounded-borders provider-activation q-pa-sm">
            <div>
              <div class="text-weight-medium">{{ t('llm.providerEnabled') }}</div>
              <div class="text-caption text-grey-7">{{ t('llm.providerEnabledHint') }}</div>
            </div>
            <q-toggle v-model="draft.is_active" color="positive" keep-color :disable="!canEdit" />
          </div>

          <q-input
            v-if="item.is_custom"
            v-model="draft.name"
            outlined
            dense
            :label="t('llm.providerName')"
            :rules="[requiredRule(t('llm.nameRequired'))]"
          />

          <template v-if="isChatGptSubscription">
            <q-select
              :model-value="draft.user_id"
              :options="users"
              option-value="id"
              option-label="label"
              emit-value
              map-options
              outlined
              dense
              :label="t('llm.chatGptOwner')"
              :hint="t('llm.chatGptOwnerHint')"
              :rules="[ownerRule]"
              :disable="!canEdit"
              @update:model-value="selectSubscriptionOwner"
            >
              <template #prepend><q-icon name="person" /></template>
            </q-select>
            <q-banner rounded class="bg-grey-2 text-grey-9">
              {{ activeUserCount === 1
                ? t('llm.chatGptSingleUserMode')
                : t('llm.chatGptMultiUserMode', { count: activeUserCount }) }}
            </q-banner>
            <q-checkbox
              v-model="draft.subscription_acknowledged"
              :label="t('llm.chatGptAcknowledge')"
              color="primary"
              :disable="!canEdit"
            />
            <div class="text-caption text-grey-7 q-ml-sm">
              {{ t('llm.chatGptAcknowledgeRequired') }}
            </div>
          </template>

          <q-input
            v-if="item.is_custom"
            v-model="draft.base_url"
            outlined
            dense
            :label="t('llm.apiUrl')"
            :rules="[requiredRule(t('llm.apiUrlRequired'))]"
          >
            <template #prepend><q-icon name="link" /></template>
          </q-input>

          <q-input
            v-for="field in item.configuration_fields"
            :key="field.key"
            v-model="configurationValues[field.key]"
            outlined
            dense
            :label="field.label"
            :placeholder="field.placeholder || undefined"
            :rules="field.required ? [requiredRule(t('llm.configurationRequired'))] : []"
          >
            <template #prepend><q-icon name="tune" /></template>
          </q-input>

          <div v-if="item.auth_type !== 'oauth_device'" class="provider-credentials">
            <div v-if="effectiveTokenUrl || item.documentation_url" class="row q-col-gutter-sm">
              <div
                v-if="effectiveTokenUrl"
                :class="item.documentation_url ? 'col-12 col-sm-7' : 'col-12'"
              >
                <q-btn
                  :href="effectiveTokenUrl"
                  target="_blank"
                  rel="noopener noreferrer"
                  color="primary"
                  outline
                  icon-right="open_in_new"
                  :label="t('llm.getApiKey')"
                  class="full-width"
                  no-caps
                />
              </div>
              <div
                v-if="item.documentation_url"
                :class="effectiveTokenUrl ? 'col-12 col-sm-5' : 'col-12'"
              >
                <q-btn
                  :href="item.documentation_url"
                  target="_blank"
                  rel="noopener noreferrer"
                  flat
                  icon-right="open_in_new"
                  :label="t('llm.documentation')"
                  class="full-width"
                  no-caps
                />
              </div>
            </div>

            <q-input
              v-model="draft.api_key"
              outlined
              dense
              :type="showApiKey ? 'text' : 'password'"
              :label="t('llm.apiKey')"
              :hint="credentialHint"
              :rules="[apiKeyRule]"
              autocomplete="off"
            >
              <template #prepend><q-icon name="key" /></template>
              <template #append>
                <q-icon
                  :name="showApiKey ? 'visibility_off' : 'visibility'"
                  class="cursor-pointer"
                  @click="showApiKey = !showApiKey"
                />
              </template>
            </q-input>
          </div>

          <q-card v-else flat bordered>
            <q-card-section class="row items-center justify-between q-gutter-sm">
              <div class="col">
                <div class="text-weight-medium">{{ t('llm.externalAccount') }}</div>
                <div class="text-caption text-grey-7">
                  {{ oauthConnected ? t('llm.externalAccountConnected') : t('llm.externalAccountNotConnected') }}
                </div>
              </div>
              <q-btn
                v-if="canEdit"
                :color="oauthConnected ? 'orange-8' : 'deep-purple'"
                :icon="oauthConnected ? 'logout' : 'login'"
                :label="oauthConnected ? t('llm.disconnectExternalAccount') : t('llm.connectExternalAccount')"
                :loading="oauthLoading"
                :disable="!oauthConnected && !subscriptionReady"
                no-caps
                @click="oauthConnected ? emit('disconnect-oauth') : connectOauth()"
              />
            </q-card-section>
          </q-card>

          <ProviderQuotaPanel
            v-if="isChatGptSubscription && oauthConnected && item.connection"
            :provider-id="item.connection.id"
          />

          <q-banner
            v-if="testResult"
            rounded
            :class="testResult.success ? 'bg-green-1 text-green-10' : 'bg-red-1 text-red-10'"
          >
            <template #avatar>
              <q-icon :name="testResult.success ? 'check_circle' : 'error'" />
            </template>
            {{ testResult.success
              ? t('llm.modelsAvailable', { provider: testResult.provider_name, count: testResult.models_count })
              : (testResult.error_details || testResult.message) }}
          </q-banner>
        </q-form>
      </component>

      <div class="provider-actions row items-center q-gutter-sm q-pa-md">
        <q-btn
          v-if="canEdit && item.is_custom"
          flat
          round
          color="negative"
          icon="delete"
          :aria-label="t('common.delete')"
          @click="emit('delete')"
        >
          <q-tooltip>{{ t('common.delete') }}</q-tooltip>
        </q-btn>
        <q-space />
        <q-btn
          v-if="canEdit && item.auth_type !== 'oauth_device'"
          flat
          color="primary"
          icon="wifi_tethering"
          :label="t('llm.testConnection')"
          :loading="testing"
          no-caps
          @click="emit('test', snapshot())"
        />
        <q-btn
          v-if="canEdit"
          color="primary"
          icon="save"
          :label="t('common.save')"
          :loading="saving"
          :disable="!subscriptionReady"
          no-caps
          @click="submit"
        />
      </div>
    </template>

    <div v-else class="col column flex-center text-center text-grey-6 q-pa-xl">
      <q-icon name="touch_app" size="54px" class="q-mb-md" />
      <div class="text-subtitle1">{{ t('llm.selectProvider') }}</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, reactive, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { QScrollArea, useQuasar, type QForm } from 'quasar'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import type {
  LLMProviderDetail,
  LLMProviderTestResponse,
  ProviderCatalogItem,
  ProviderUserOption,
} from '../services/llmProviderService'
import type { ProviderConfigurationDraft } from '../providerUi'
import { customProviderType } from '../customProviderTypes'
import ProviderAvatar from './ProviderAvatar.vue'
import ProviderQuotaPanel from './ProviderQuotaPanel.vue'

const $q = useQuasar()

const props = defineProps<{
  item: ProviderCatalogItem | null
  detail: LLMProviderDetail | null
  saving?: boolean
  testing?: boolean
  oauthLoading?: boolean
  testResult?: LLMProviderTestResponse | null
  users: ProviderUserOption[]
  activeUserCount: number
}>()

const emit = defineEmits<{
  save: [draft: ProviderConfigurationDraft]
  'auto-save': [draft: ProviderConfigurationDraft]
  change: []
  test: [draft: ProviderConfigurationDraft]
  'connect-oauth': [draft: ProviderConfigurationDraft]
  'disconnect-oauth': []
  delete: []
}>()

const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.LLM_PROVIDER_EDIT))

const { t } = useI18n()
const providerForm = useTemplateRef<QForm>('providerForm')
const showApiKey = ref(false)
const loadedItemKey = ref<string | null>(null)
const editableFields = ['name', 'provider_type', 'base_url', 'is_active', 'user_id', 'subscription_acknowledged'] as const
const editedFields = new Set<keyof ProviderConfigurationDraft>()
const editedConfiguration = new Set<string>()
const draft = reactive<ProviderConfigurationDraft>({
  name: '',
  provider_type: 'openai_compatible',
  base_url: '',
  api_key: null,
  configuration: {},
  is_active: false,
  user_id: null,
  subscription_acknowledged: false,
})
const configurationValues = reactive<Record<string, string>>({})
let resettingDraft = false

const oauthConnected = computed(() => Boolean(props.item?.connection?.oauth_connected))
const isChatGptSubscription = computed(() => props.item?.code === 'openai-codex')
const subscriptionReady = computed(() => (
  !isChatGptSubscription.value
  || (draft.user_id !== null && draft.subscription_acknowledged)
))
const effectiveTokenUrl = computed(() => (
  props.item?.is_custom ? null : (props.item?.token_url || null)
))
const credentialHint = computed(() => {
  if (props.item?.connection?.api_key_configured && !draft.api_key) {
    return t('llm.apiKeyAlreadyConfigured')
  }
  return props.item?.api_key_required ? t('llm.apiKeyPasteHint') : t('llm.apiKeyOptionalHint')
})
const guideText = computed(() => {
  if (props.item?.auth_type === 'oauth_device') return t('llm.oauthGuide')
  if (props.item?.is_custom) {
    return t(customProviderType(props.item.provider_type).guideKey)
  }
  if (props.item?.auth_type === 'optional_api_key') return t('llm.publicCatalogGuide')
  return t('llm.apiKeyGuide')
})

function requiredRule(message: string): (value: string | null) => true | string {
  return value => Boolean(value?.trim()) || message
}

function apiKeyRule(value: string | null): true | string {
  if (!draft.is_active || !props.item?.api_key_required) return true
  if (value?.trim() || props.item.connection?.api_key_configured) return true
  return t('llm.apiKeyRequired')
}

function ownerRule(value: number | null): true | string {
  return value !== null || t('llm.chatGptOwnerRequired')
}

function selectSubscriptionOwner(userId: number | null): void {
  if (draft.user_id !== userId) draft.subscription_acknowledged = false
  draft.user_id = userId
}

function resetDraft(): void {
  const item = props.item
  if (!item) return
  resettingDraft = true
  const connection = props.detail || item.connection
  const sameItem = loadedItemKey.value === item.key
  if (!sameItem) {
    editedFields.clear()
    editedConfiguration.clear()
  }
  const nextConfiguration: Record<string, string> = {}
  for (const field of item.configuration_fields) {
    const value = connection?.configuration?.[field.key]
    nextConfiguration[field.key] = value === null || value === undefined ? '' : String(value)
  }
  const next: ProviderConfigurationDraft = {
    name: connection?.name || item.display_name,
    provider_type: item.provider_type,
    base_url: item.is_custom ? (connection?.base_url || item.default_base_url) : item.default_base_url,
    api_key: null,
    configuration: nextConfiguration,
    is_active: connection?.is_active ?? false,
    user_id: connection?.user_id ?? null,
    subscription_acknowledged: connection?.subscription_acknowledged ?? false,
  }
  // Refresh unchanged fields, but never overwrite edits made while a request was pending.
  const preserved: Partial<ProviderConfigurationDraft> = {}
  if (sameItem) {
    for (const field of editableFields) {
      if (editedFields.has(field)) Object.assign(preserved, { [field]: draft[field] })
    }
    preserved.api_key = draft.api_key
  }
  const previousConfiguration = { ...configurationValues }
  for (const key of Object.keys(configurationValues)) delete configurationValues[key]
  for (const [key, value] of Object.entries(nextConfiguration)) {
    configurationValues[key] = editedConfiguration.has(key)
      ? previousConfiguration[key] ?? '' : value
  }
  Object.assign(draft, next, preserved, { configuration: configurationValues })
  loadedItemKey.value = item.key
  if (!sameItem) showApiKey.value = false
  resettingDraft = false
}

function snapshot(): ProviderConfigurationDraft {
  return { ...draft, api_key: draft.api_key?.trim() || null, configuration: { ...configurationValues } }
}

function readyToSave(): boolean {
  const item = props.item
  if (!item || !subscriptionReady.value) return false
  if (item.is_custom && (!draft.name.trim() || !draft.base_url.trim())) return false
  if (apiKeyRule(draft.api_key) !== true) return false
  return item.configuration_fields.every(field => !field.required || configurationValues[field.key]?.trim())
}

watch(
  () => JSON.stringify(snapshot()),
  (value, previous) => {
    if (resettingDraft) return
    const current = JSON.parse(value) as ProviderConfigurationDraft
    const before = JSON.parse(previous) as ProviderConfigurationDraft
    for (const field of editableFields) {
      if (current[field] !== before[field]) editedFields.add(field)
    }
    for (const key of Object.keys(current.configuration)) {
      if (current.configuration[key] !== before.configuration[key]) editedConfiguration.add(key)
    }
    emit('change')
    if (!canEdit.value) return
    if ((draft.is_active && readyToSave()) || (before.is_active && !draft.is_active)) {
      emit('auto-save', snapshot())
    }
  },
  { flush: 'sync' },
)

async function submit(): Promise<void> {
  if (!canEdit.value || !subscriptionReady.value) return
  if (await providerForm.value?.validate() === false) return
  emit('save', snapshot())
}

async function connectOauth(): Promise<void> {
  if (!canEdit.value || !subscriptionReady.value) return
  const valid = await providerForm.value?.validate()
  if (valid === false) return
  emit('connect-oauth', { ...draft, configuration: { ...configurationValues } })
}

watch(
  () => [props.item?.key, props.detail] as const,
  resetDraft,
  { immediate: true },
)
</script>

<style scoped>
.provider-config-panel {
  min-height: 640px;
  background: var(--q-background, #fff);
}

.provider-config-scroll {
  min-height: 0;
  overflow-y: auto;
}

.provider-panel-header,
.provider-actions {
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}

.provider-actions {
  border-top: 1px solid rgba(0, 0, 0, 0.08);
  border-bottom: 0;
}

.provider-guide {
  font-size: 0.82rem;
}

.provider-credentials {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.provider-activation {
  background: rgba(0, 0, 0, 0.035);
}

body.body--dark .provider-panel-header,
body.body--dark .provider-actions {
  border-color: rgba(255, 255, 255, 0.12);
}

body.body--dark .provider-activation {
  background: rgba(255, 255, 255, 0.05);
}

@media (min-width: 1280px) {
  .provider-config-panel {
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }

  .provider-panel-header,
  .provider-actions {
    flex-shrink: 0;
  }

  .provider-config-scroll {
    overflow: hidden;
  }
}

@media (max-width: 1279px) {
  .provider-config-panel {
    min-height: 0;
  }

  .provider-config-scroll {
    flex: none;
    overflow: visible;
  }

  .provider-actions {
    flex-wrap: wrap;
  }
}
</style>
