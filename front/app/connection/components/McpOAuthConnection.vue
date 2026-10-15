<template>
  <q-card flat bordered>
    <q-card-section>
      <div class="text-subtitle2">{{ t('connection.oauth.title') }}</div>
      <div class="q-my-sm" role="status">
        {{ loading ? t('connection.oauth.loading') : t(statusKey) }}
      </div>
      <q-banner v-if="error" role="alert" class="q-mb-sm">
        <div class="text-weight-medium">{{ t('connection.oauth.errorTitle') }}</div>
        <div class="oauth-error-detail">{{ error }}</div>
        <template #action><q-btn flat :label="t('connection.oauth.retry')" :disable="busy || loading" @click="retryAction()" /></template>
      </q-banner>
      <div v-if="deviceAuthorization && canEdit" class="q-mb-md">
        <p>{{ t('connection.oauth.deviceInstructions') }}</p>
        <p><code>{{ deviceAuthorization.user_code }}</code></p>
        <q-btn color="primary" no-caps :label="t('connection.oauth.deviceOpen')" :href="deviceAuthorization.verification_uri" target="_blank" rel="noopener noreferrer" />
        <p class="q-mt-sm">{{ t('connection.oauth.deviceWaiting') }}</p>
      </div>
      <q-form v-if="clientConfiguration && canEdit" class="q-mb-md" @submit="authorize">
        <p>{{ t('connection.oauth.clientInstructions') }}</p>
        <p class="oauth-error-detail"><code>{{ clientConfiguration }}</code></p>
        <q-input v-model="clientId" outlined :label="t('connection.oauth.clientId')" autocomplete="off" :rules="[value => !!String(value).trim() || t('connection.oauth.clientIdRequired')]" />
        <q-input v-model="clientSecret" outlined type="password" :label="t('connection.oauth.clientSecret')" autocomplete="new-password" class="q-mb-md" />
        <q-btn type="submit" color="primary" no-caps :loading="busy" :label="t('connection.oauth.clientConnect')" />
      </q-form>
      <div v-if="localAuthorization && canEdit" class="q-mb-md">
        <div class="text-weight-medium">{{ t('connection.oauth.localTitle') }}</div>
        <p>{{ t('connection.oauth.localInstructions') }}</p>
        <p><code>python3 galaris-connect.py</code></p>
        <q-btn color="primary" no-caps :label="t('connection.oauth.localDownload')" @click="downloadRelay" />
        <div class="q-mt-sm">
          <a :href="localAuthorization.authorization_url" target="_blank" rel="noopener noreferrer">{{ t('connection.oauth.localOpen') }}</a>
        </div>
      </div>
      <div class="row q-gutter-sm">
        <q-btn v-if="canEdit && !clientConfiguration" color="primary" :icon="status?.connected ? 'logout' : 'login'"
          :label="t(status?.connected ? 'connection.oauth.disconnect' : 'connection.oauth.authorize')"
          :loading="busy" :disable="(!connectionId && !prepareConnection) || loading" no-caps
          @click="status?.connected ? disconnect() : authorize()" />
      </div>
      <div v-if="!connectionId && !prepareConnection" class="text-caption q-mt-sm">{{ t('connection.oauth.saveFirst') }}</div>
    </q-card-section>
  </q-card>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { mcpOAuthService, type McpOAuthStart, type McpOAuthStatus } from '../services/mcpOAuthService'

const props = defineProps<{ connectionId: number | null; canEdit: boolean; prepareConnection?: () => Promise<number> }>()
const { t } = useI18n()
const status = ref<McpOAuthStatus | null>(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const localAuthorization = ref<{ authorization_url: string; local_script: string } | null>(null)
const deviceAuthorization = ref<NonNullable<McpOAuthStart['device']> & { connectionId: number } | null>(null)
const clientConfiguration = ref('')
const clientId = ref('')
const clientSecret = ref('')
let pollTimer: ReturnType<typeof setTimeout> | undefined
let pollAbort: AbortController | null = null
let retryAction: () => Promise<void> = load
let generation = 0
const statusKey = computed(() => localAuthorization.value || deviceAuthorization.value ? 'connection.oauth.pending' : status.value?.connected ? 'connection.oauth.connected'
  : status.value?.reconnect_required ? 'connection.oauth.reconnectRequired'
    : status.value?.pending ? 'connection.oauth.pending' : 'connection.oauth.disconnected')

function errorMessage(cause: unknown): string {
  return apiErrorDetail(cause) || t('connection.oauth.failed')
}

function stopPolling(): void {
  clearTimeout(pollTimer)
  pollAbort?.abort()
  pollAbort = null
  deviceAuthorization.value = null
}

async function pollDevice(current: number): Promise<void> {
  const device = deviceAuthorization.value
  if (current !== generation || !device) return
  const controller = new AbortController()
  pollAbort = controller
  error.value = ''
  try {
    const result = await mcpOAuthService.pollDevice(device.connectionId, device.state, controller.signal)
    if (current !== generation || controller.signal.aborted) return
    if (result.connected) await load()
    else pollTimer = setTimeout(() => { void pollDevice(current) }, Math.max(1, result.interval) * 1000)
  } catch (cause) {
    if (current === generation && !controller.signal.aborted) {
      error.value = errorMessage(cause)
      retryAction = () => pollDevice(current)
    }
  } finally { if (pollAbort === controller) pollAbort = null }
}

async function load(): Promise<void> {
  const current = ++generation
  stopPolling()
  const id = props.connectionId
  status.value = null
  error.value = ''
  localAuthorization.value = null
  clientConfiguration.value = ''
  clientId.value = ''
  clientSecret.value = ''
  loading.value = Boolean(id)
  if (!id) return
  try {
    const result = await mcpOAuthService.status(id)
    if (current === generation) status.value = result
  } catch (cause) {
    if (current === generation) { error.value = errorMessage(cause); retryAction = load }
  } finally {
    if (current === generation) loading.value = false
  }
}

async function authorize(): Promise<void> {
  if (busy.value || !props.canEdit) return
  if (clientConfiguration.value && !clientId.value.trim()) return
  const current = generation
  stopPolling()
  busy.value = true
  error.value = ''
  localAuthorization.value = null
  try {
    const id = props.prepareConnection ? await props.prepareConnection() : props.connectionId
    if (!id || current !== generation) return
    const client = clientConfiguration.value ? { client_id: clientId.value.trim(), client_secret: clientSecret.value || undefined } : undefined
    const result = await mcpOAuthService.start(id, client)
    if (current !== generation) return
    if (result.method === 'configure') clientConfiguration.value = result.redirect_uri ?? ''
    else if (result.method === 'device' && result.device) {
      deviceAuthorization.value = { ...result.device, connectionId: id }
      pollTimer = setTimeout(() => { void pollDevice(current) }, Math.max(1, result.device.interval) * 1000)
    } else if (result.local_script) localAuthorization.value = { authorization_url: result.authorization_url, local_script: result.local_script }
    else window.location.assign(result.authorization_url)
    if (result.method !== 'configure') {
      clientConfiguration.value = ''
      clientId.value = ''
      clientSecret.value = ''
    }
  } catch (cause) {
    if (current === generation) { error.value = errorMessage(cause); retryAction = authorize }
  } finally { busy.value = false }
}

function downloadRelay(): void {
  if (!localAuthorization.value) return
  const url = URL.createObjectURL(new Blob([localAuthorization.value.local_script], { type: 'text/x-python;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'galaris-connect.py'
  link.click()
  URL.revokeObjectURL(url)
}

async function disconnect(): Promise<void> {
  const id = props.connectionId
  if (!id || busy.value || !props.canEdit) return
  const current = generation
  busy.value = true
  error.value = ''
  try {
    await mcpOAuthService.disconnect(id)
    if (current === generation) await load()
  } catch (cause) {
    if (current === generation) { error.value = errorMessage(cause); retryAction = disconnect }
  } finally { busy.value = false }
}

watch(() => props.connectionId, load, { immediate: true })
onBeforeUnmount(() => { generation++; stopPolling(); clientSecret.value = '' })
</script>

<style scoped>
.oauth-error-detail { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
