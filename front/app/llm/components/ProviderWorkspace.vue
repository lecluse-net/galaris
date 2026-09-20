<template>
  <div class="provider-workspace-container">
    <q-card flat bordered class="provider-workspace overflow-hidden">
      <div class="provider-workspace-grid">
        <ProviderListPanel
          :items="store.catalogItems"
          :selected-key="selectedKey"
          :loading="initialLoading"
          @select="selectedKey = $event"
          @add="customDialog = true"
        />

        <ProviderConfigPanel
          :item="selectedItem"
          :detail="selectedDetail"
          :saving="saving"
          :testing="testing"
          :oauth-loading="oauthLoading"
          :test-result="testResult"
          :users="store.providerUsers"
          :active-user-count="store.activeUserCount"
          @save="saveProvider"
          @test="testProvider"
          @connect-oauth="connectOauth"
          @disconnect-oauth="disconnectOauth"
          @delete="deleteDialog = true"
        />

        <ProviderModelsPanel
          :item="selectedItem"
          :capability="selectedCapability"
          :models="models"
          :configured-llms="store.llms"
          :loading="loadingModels"
          :managing="managingModel"
          :error="modelError"
          @refresh="loadModels(true)"
          @update:capability="changeCapability"
          @create-llm="createLlm"
          @pull="pullModel"
          @delete-model="deleteModel"
        />
      </div>
    </q-card>

    <CustomProviderDialog
      v-model="customDialog"
      :saving="savingCustom"
      @create="createCustomProvider"
    />

    <q-dialog v-model="oauthDialog" @hide="stopOauthPolling">
      <q-card style="width: 540px; max-width: 94vw">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ t('llm.connectExternalAccount') }}</div>
          <q-space />
          <q-btn flat round dense icon="close" :aria-label="$t('common.close')" @click="closeOauthDialog" />
        </q-card-section>
        <q-separator />
        <q-card-section v-if="!oauthChallenge" class="column flex-center q-pa-xl">
          <q-spinner color="deep-purple" size="42px" />
          <div class="q-mt-md">{{ t('llm.providerLoginPreparing') }}</div>
        </q-card-section>
        <q-card-section v-else class="text-center q-pa-lg">
          <q-icon name="open_in_browser" color="deep-purple" size="44px" />
          <div class="text-subtitle1 q-mt-md">{{ t('llm.providerDeviceInstructions') }}</div>
          <q-btn
            :href="oauthChallenge.verification_uri"
            target="_blank"
            rel="noopener noreferrer"
            color="deep-purple"
            icon-right="open_in_new"
            :label="t('llm.openOpenAi')"
            class="q-my-lg"
          />
          <div class="text-caption text-grey-7">{{ t('llm.providerCodeLabel') }}</div>
          <div class="oauth-code text-h4 text-weight-bold q-my-sm">{{ oauthChallenge.user_code }}</div>
          <q-btn flat color="primary" icon="content_copy" :label="t('llm.copyCode')" @click="copyOauthCode" />
          <div class="row flex-center q-gutter-sm q-mt-lg text-grey-7">
            <q-spinner-dots color="deep-purple" size="28px" />
            <span>{{ t('llm.providerLoginWaiting') }}</span>
          </div>
        </q-card-section>
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
          {{ t('llm.confirmDeleteProvider', { name: selectedItem?.display_name }) }}
        </q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn v-if="canEdit" color="negative" :label="t('common.delete')" :loading="saving" @click="deleteCustomProvider" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { copyToClipboard, useInterval, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import ProviderListPanel from './ProviderListPanel.vue'
import ProviderConfigPanel from './ProviderConfigPanel.vue'
import ProviderModelsPanel from './ProviderModelsPanel.vue'
import CustomProviderDialog from './CustomProviderDialog.vue'
import { useLLMProviderStore } from '../stores/llmProviderStore'
import type {
  ProviderDeviceStartResponse,
  LLMModelInfo,
  LLMProvider,
  LLMProviderCreate,
  LLMProviderDetail,
  LLMProviderTestResponse,
  ProviderCatalogItem,
  AICapability,
} from '../services/llmProviderService'
import type { ProviderConfigurationDraft } from '../providerUi'

const emit = defineEmits<{
  'create-llm': [payload: { providerId: number; model: LLMModelInfo }]
}>()

const store = useLLMProviderStore()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.LLM_PROVIDER_EDIT))
const $q = useQuasar()
const { t } = useI18n()
const { registerInterval, removeInterval } = useInterval()

const selectedKey = ref<string | null>(null)
const selectedDetail = ref<LLMProviderDetail | null>(null)
const models = ref<LLMModelInfo[]>([])
const selectedCapability = ref<AICapability>('chat')
const modelError = ref<string | null>(null)
const initialLoading = ref(true)
const loadingModels = ref(false)
const saving = ref(false)
const testing = ref(false)
const testResult = ref<LLMProviderTestResponse | null>(null)
const customDialog = ref(false)
const savingCustom = ref(false)
const deleteDialog = ref(false)
const managingModel = ref(false)
const oauthLoading = ref(false)
const oauthDialog = ref(false)
const oauthChallenge = ref<ProviderDeviceStartResponse | null>(null)
let selectionGeneration = 0
let oauthPollInFlight = false
let oauthExpiresAt = 0

const selectedItem = computed<ProviderCatalogItem | null>(() =>
  store.catalogItems.find(item => item.key === selectedKey.value) || null,
)

function chooseSelection(): void {
  if (selectedKey.value && store.catalogItems.some(item => item.key === selectedKey.value)) return
  selectedKey.value = (
    store.catalogItems.find(item => item.connection?.is_active)
    || store.catalogItems[0]
  )?.key || null
}

function canLoadModels(item: ProviderCatalogItem | null): boolean {
  return Boolean(
    item
    && (
      (item.connection && (item.auth_type !== 'oauth_device' || item.connection.oauth_connected))
      || (!item.connection && !item.is_custom && item.auth_type === 'optional_api_key')
    ),
  )
}

async function loadSelection(item: ProviderCatalogItem | null): Promise<void> {
  const generation = ++selectionGeneration
  selectedDetail.value = null
  models.value = []
  modelError.value = null
  testResult.value = null
  if (item && !item.capabilities.includes(selectedCapability.value)) {
    selectedCapability.value = item.capabilities[0] || 'chat'
  }
  if (!item?.connection) {
    if (generation === selectionGeneration && canLoadModels(item)) {
      await loadModels(false, generation)
    }
    return
  }

  try {
    await store.fetchProvider(item.connection.id)
    if (generation !== selectionGeneration) return
    selectedDetail.value = store.currentProvider
  } catch (error) {
    if (generation === selectionGeneration) modelError.value = errorMessage(error)
    return
  }

  if (generation === selectionGeneration && canLoadModels(item)) {
    await loadModels(false, generation)
  }
}

async function loadModels(force = false, expectedGeneration = selectionGeneration): Promise<void> {
  const item = selectedItem.value
  const providerId = item?.connection?.id
  if (!item || !canLoadModels(item)) {
    models.value = []
    return
  }

  loadingModels.value = true
  modelError.value = null
  try {
    const result = providerId
      ? await store.fetchProviderResources(providerId, selectedCapability.value, force)
      : await store.fetchCatalogResources(item.code!, selectedCapability.value, force)
    if (expectedGeneration !== selectionGeneration) return
    models.value = result.models
  } catch (error) {
    if (expectedGeneration === selectionGeneration) {
      models.value = []
      modelError.value = errorMessage(error)
    }
  } finally {
    if (expectedGeneration === selectionGeneration) loadingModels.value = false
  }
}

function changeCapability(capability: AICapability): void {
  if (selectedCapability.value === capability) return
  selectedCapability.value = capability
  models.value = []
  void loadModels(false)
}

async function saveProvider(draft: ProviderConfigurationDraft): Promise<void> {
  if (!canEdit.value) return
  const item = selectedItem.value
  if (!item) return
  saving.value = true
  try {
    let provider: LLMProvider
    if (item.is_custom && item.connection) {
      provider = await store.updateProvider(item.connection.id, {
        name: draft.name,
        provider_type: draft.provider_type,
        base_url: draft.base_url,
        ...(draft.api_key !== null ? { api_key: draft.api_key } : {}),
        is_active: draft.is_active,
        configuration: draft.configuration,
        user_id: draft.user_id,
        subscription_acknowledged: draft.subscription_acknowledged,
      })
    } else if (item.code) {
      provider = await store.configureCatalogProvider(item.code, {
        ...(draft.api_key !== null ? { api_key: draft.api_key } : {}),
        is_active: draft.is_active,
        configuration: draft.configuration,
        user_id: draft.user_id,
        subscription_acknowledged: draft.subscription_acknowledged,
      })
    } else {
      return
    }
    chooseSelection()
    await loadSelection(store.catalogItems.find(entry => entry.key === selectedKey.value) || null)
    $q.notify({ type: 'positive', message: t('llm.notify.providerUpdated') })
    if (provider.is_active && canLoadModels(selectedItem.value)) await loadModels(true)
  } catch (error) {
    $q.notify({ type: 'negative', message: errorMessage(error) || t('llm.notify.saveError') })
  } finally {
    saving.value = false
  }
}

async function testProvider(draft: ProviderConfigurationDraft): Promise<void> {
  if (!canEdit.value) return
  const item = selectedItem.value
  if (!item || item.auth_type === 'oauth_device') return
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await store.testConnection({
      provider_id: item.connection?.id,
      base_url: draft.base_url,
      api_key: draft.api_key,
      provider_type: draft.provider_type,
      catalog_code: item.code,
      configuration: draft.configuration,
    })
    if (testResult.value.success) {
      $q.notify({
        type: 'positive',
        message: t('llm.notify.connectionSuccess', { count: testResult.value.models_count }),
      })
    }
  } catch (error) {
    $q.notify({ type: 'negative', message: errorMessage(error) || t('llm.notify.testConnectionError') })
  } finally {
    testing.value = false
  }
}

async function createCustomProvider(data: LLMProviderCreate): Promise<void> {
  if (!canEdit.value) return
  savingCustom.value = true
  try {
    const provider = await store.createProvider(data)
    selectedKey.value = `custom:${provider.id}`
    customDialog.value = false
    await loadSelection(store.catalogItems.find(item => item.key === selectedKey.value) || null)
    $q.notify({ type: 'positive', message: t('llm.notify.providerCreated') })
  } catch (error) {
    $q.notify({ type: 'negative', message: errorMessage(error) || t('llm.notify.saveError') })
  } finally {
    savingCustom.value = false
  }
}

async function deleteCustomProvider(): Promise<void> {
  if (!canEdit.value) return
  const provider = selectedItem.value?.connection
  if (!provider || !selectedItem.value?.is_custom) return
  saving.value = true
  try {
    await store.deleteProvider(provider.id)
    deleteDialog.value = false
    selectedKey.value = null
    chooseSelection()
    $q.notify({ type: 'positive', message: t('llm.notify.providerDeleted') })
  } catch (error) {
    $q.notify({ type: 'negative', message: errorMessage(error) || t('llm.notify.deleteError') })
  } finally {
    saving.value = false
  }
}

async function ensureOauthConnection(draft: ProviderConfigurationDraft): Promise<LLMProvider | null> {
  const item = selectedItem.value
  if (!item?.code) return null
  return store.configureCatalogProvider(item.code, {
    is_active: true,
    configuration: draft.configuration,
    user_id: draft.user_id,
    subscription_acknowledged: draft.subscription_acknowledged,
  })
}

async function connectOauth(draft: ProviderConfigurationDraft): Promise<void> {
  if (!canEdit.value) return
  oauthLoading.value = true
  oauthDialog.value = true
  oauthChallenge.value = null
  stopOauthPolling()
  try {
    const provider = await ensureOauthConnection(draft)
    if (!provider) throw new Error(t('llm.notify.providerLoginError'))
    const challenge = await store.startProviderDeviceLogin(provider.id)
    oauthChallenge.value = challenge
    oauthExpiresAt = Date.now() + challenge.expires_in * 1000
    registerInterval(() => { void pollOauth(provider.id) }, Math.max(1000, challenge.interval * 1000))
  } catch (error) {
    closeOauthDialog()
    $q.notify({ type: 'negative', message: errorMessage(error) || t('llm.notify.providerLoginError') })
  } finally {
    oauthLoading.value = false
  }
}

async function pollOauth(providerId: number): Promise<void> {
  if (!oauthChallenge.value || oauthPollInFlight) return
  if (Date.now() >= oauthExpiresAt) {
    $q.notify({ type: 'warning', message: t('llm.notify.providerLoginExpired') })
    closeOauthDialog()
    return
  }
  oauthPollInFlight = true
  try {
    const result = await store.pollProviderDeviceLogin(providerId, oauthChallenge.value)
    if (result.status !== 'connected') return
    stopOauthPolling()
    await store.refreshProviders()
    chooseSelection()
    await loadSelection(selectedItem.value)
    oauthDialog.value = false
    $q.notify({ type: 'positive', message: t('llm.notify.providerConnected') })
  } catch (error) {
    stopOauthPolling()
    oauthDialog.value = false
    $q.notify({ type: 'negative', message: errorMessage(error) || t('llm.notify.providerLoginError') })
  } finally {
    oauthPollInFlight = false
  }
}

async function disconnectOauth(): Promise<void> {
  if (!canEdit.value) return
  const providerId = selectedItem.value?.connection?.id
  if (!providerId) return
  oauthLoading.value = true
  try {
    await store.disconnectProviderAuthentication(providerId)
    await store.refreshProviders()
    models.value = []
    $q.notify({ type: 'positive', message: t('llm.notify.providerDisconnected') })
  } catch (error) {
    $q.notify({ type: 'negative', message: errorMessage(error) || t('llm.notify.providerDisconnectError') })
  } finally {
    oauthLoading.value = false
  }
}

function stopOauthPolling(): void {
  removeInterval()
  oauthPollInFlight = false
}

function closeOauthDialog(): void {
  stopOauthPolling()
  oauthDialog.value = false
  oauthChallenge.value = null
}

async function copyOauthCode(): Promise<void> {
  if (!oauthChallenge.value) return
  try {
    await copyToClipboard(oauthChallenge.value.user_code)
    $q.notify({ type: 'positive', message: t('llm.notify.codeCopied') })
  } catch (error) {
    console.error('Unable to copy OAuth code:', error)
  }
}

function createLlm(model: LLMModelInfo): void {
  const providerId = selectedItem.value?.connection?.id
  if (providerId) {
    emit('create-llm', {
      providerId,
      model: {
        ...model,
        service_capabilities: model.service_capabilities.length
          ? model.service_capabilities
          : [selectedCapability.value],
      },
    })
  }
}

async function pullModel(modelName: string): Promise<void> {
  if (!canEdit.value) return
  const providerId = selectedItem.value?.connection?.id
  if (!providerId) return
  managingModel.value = true
  try {
    const result = await store.pullModel(providerId, modelName)
    $q.notify({ type: 'positive', message: result.message })
    await loadModels(true)
  } catch (error) {
    $q.notify({ type: 'negative', message: errorMessage(error) || t('llm.notify.pullModelError') })
  } finally {
    managingModel.value = false
  }
}

async function deleteModel(modelName: string): Promise<void> {
  if (!canEdit.value) return
  const providerId = selectedItem.value?.connection?.id
  if (!providerId) return
  managingModel.value = true
  try {
    const result = await store.deleteModel(providerId, modelName)
    $q.notify({ type: 'positive', message: result.message })
    await loadModels(true)
  } catch (error) {
    $q.notify({ type: 'negative', message: errorMessage(error) || t('llm.notify.deleteModelError') })
  } finally {
    managingModel.value = false
  }
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
  return error instanceof Error ? error.message : String(error || '')
}

watch(selectedItem, item => { void loadSelection(item) })

onMounted(async () => {
  initialLoading.value = true
  try {
    await Promise.all([store.fetchCatalog(), store.fetchProviders(), store.fetchLLMs()])
    chooseSelection()
  } catch (error) {
    $q.notify({ type: 'negative', message: errorMessage(error) || t('llm.notify.fetchProvidersError') })
  } finally {
    initialLoading.value = false
  }
})

onUnmounted(stopOauthPolling)
</script>

<style scoped>
.provider-workspace-grid {
  display: grid;
  grid-template-columns: 280px repeat(2, minmax(0, 1fr));
  min-height: 640px;
  min-width: 0;
}

.provider-workspace-grid > * {
  min-width: 0;
}

.provider-workspace-grid > :not(:last-child) {
  border-right: 1px solid rgba(0, 0, 0, 0.1);
}

.oauth-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  letter-spacing: 0.14em;
}

body.body--dark .provider-workspace-grid > :not(:last-child) {
  border-right-color: rgba(255, 255, 255, 0.12);
}

@media (min-width: 1280px) {
  .provider-workspace-container,
  .provider-workspace,
  .provider-workspace-grid {
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }

  .provider-workspace-grid {
    grid-template-columns: 280px repeat(2, minmax(0, 1fr));
    grid-template-rows: minmax(0, 1fr);
  }
}

@media (max-width: 1279px) {
  .provider-workspace-grid {
    display: block;
    min-height: 0;
  }

  .provider-workspace-grid > * {
    border-right: 0 !important;
    border-bottom: 1px solid rgba(0, 0, 0, 0.1);
  }

  .provider-workspace-grid > :last-child {
    border-top: 0;
    border-bottom: 0;
  }

  body.body--dark .provider-workspace-grid > * {
    border-bottom-color: rgba(255, 255, 255, 0.12);
  }
}
</style>
