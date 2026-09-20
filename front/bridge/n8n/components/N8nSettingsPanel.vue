<template>
  <section class="n8n-settings">
    <h3 class="text-subtitle1 q-mt-none">{{ t('n8nSetup.title') }}</h3>
    <p class="text-body2">{{ t('n8nSetup.intro') }}</p>
    <q-banner v-if="loadError" class="n8n-status n8n-status--error q-mb-md" role="alert">
      {{ t('n8nSetup.loadError') }}
      <template #action><q-btn flat :label="t('common.retry')" @click="loadDefaults" /></template>
    </q-banner>
    <q-form autocomplete="off" @submit="save(true)">
      <div class="n8n-fields">
        <div v-for="field in fields.filter(item => !item.advanced)" :key="field.name">
          <q-input v-model="form[field.name]" outlined dense :label="t(field.label)"
            :type="field.secret ? 'password' : 'url'" :readonly="!canEdit || busy"
            :name="field.name" :autocomplete="field.secret ? 'new-password' : 'off'" autocapitalize="none" :spellcheck="false"
            :placeholder="configured(field.name) ? t('configuration.secretUnchanged') : undefined">
            <template v-if="field.secret && configured(field.name)" #append>
              <q-icon name="verified_user" color="positive"><q-tooltip>{{ t('configuration.secretConfigured') }}</q-tooltip></q-icon>
              <q-btn v-if="canEdit" flat round dense icon="delete_outline" :disable="busy"
                :aria-label="t('configuration.clearSecret')" @click="clearSecret(field.name)" />
            </template>
          </q-input>
          <div class="text-caption q-mt-xs">{{ t(field.hint) }}</div>
        </div>
      </div>

      <div class="n8n-addresses q-my-md">
        <div class="text-weight-medium">{{ t('n8nSetup.addresses') }}</div>
        <div>{{ t('n8nSetup.webhookAddress') }} <strong>{{ webhookUrl || t('n8nSetup.enterUrl') }}</strong></div>
        <div>{{ t('n8nSetup.galarisAddress') }} <strong>{{ galarisUrl || t('n8nSetup.notAvailable') }}</strong></div>
        <div class="text-caption q-mt-xs">{{ t('n8nSetup.addressHint') }}</div>
      </div>

      <q-expansion-item icon="tune" :label="t('n8nSetup.advanced')" class="q-mb-md">
        <div class="n8n-fields q-pa-sm">
          <div v-for="field in fields.filter(item => item.advanced)" :key="field.name">
            <q-input v-model="form[field.name]" outlined dense :label="t(field.label)"
              :type="field.secret ? 'password' : field.name.endsWith('_URL') ? 'url' : 'text'" :readonly="!canEdit || busy"
              :name="field.name" :autocomplete="field.secret ? 'new-password' : 'off'" autocapitalize="none" :spellcheck="false"
              :placeholder="configured(field.name) ? t('configuration.secretUnchanged') : undefined">
              <template v-if="field.secret && configured(field.name)" #append>
                <q-icon name="verified_user" color="positive"><q-tooltip>{{ t('configuration.secretConfigured') }}</q-tooltip></q-icon>
                <q-btn v-if="canEdit" flat round dense icon="delete_outline" :disable="busy"
                  :aria-label="t('configuration.clearSecret')" @click="clearSecret(field.name)" />
              </template>
            </q-input>
            <div class="text-caption q-mt-xs">{{ t(field.hint) }}</div>
            <div v-if="field.secret && canEdit" class="row q-gutter-sm q-mt-xs">
              <q-btn outline no-caps :disable="busy" :label="t('n8nSetup.generateSecret')" @click="generateSecret" />
              <q-btn v-if="form[field.name]" flat no-caps :disable="busy" icon="content_copy"
                :label="t('n8nSetup.copySecret')" @click="copySecret" />
            </div>
          </div>
        </div>
      </q-expansion-item>

      <div v-if="canEdit" class="n8n-actions">
        <q-btn type="submit" color="primary" icon="health_and_safety" no-caps
          :label="t('n8nSetup.test')" :loading="busy" :disable="loading || loadError || !initialized" />
        <q-btn outline color="primary" no-caps :label="t('common.save')"
          :disable="busy || loading || loadError || !initialized" @click="save(false)" />
      </div>
      <p v-if="canEdit" class="text-caption q-mt-sm">{{ t('n8nSetup.saveBeforeTest') }}</p>
    </q-form>

    <q-banner v-if="result" class="n8n-status q-mt-md" :class="{ 'n8n-status--error': !result.ok }" role="status">
      <template #avatar><q-icon :name="result.ok ? 'check_circle' : 'error'" /></template>
      {{ result.message }}
    </q-banner>
    <p class="text-caption q-mt-md">{{ t('n8nSetup.testScope') }}</p>
    <q-btn v-if="canReadProcesses" to="/process" outline no-caps icon="account_tree" :label="t('n8nSetup.openProcesses')" />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { copyToClipboard, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useParamsStore } from '@/core/params'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { showConfirmationDialog } from '@/core/util'
import { configurationService } from '../services/configurationService'

const { t, te } = useI18n()
const $q = useQuasar()
const params = useParamsStore()
const access = usePrivilegeStore()
const canEdit = computed(() => access.hasPrivilege(privileges.PARAMS_EDIT))
const canReadProcesses = computed(() => access.hasPrivilege(privileges.PROCESS_READ) || access.hasPrivilege(privileges.PROCESS_ADMIN))
const fields = [
  { name: 'PROCESS_N8N_BASE_URL', label: 'processSettings.fields.baseUrl', hint: 'n8nSetup.urlHint', advanced: false, secret: false },
  { name: 'PROCESS_N8N_API_TOKEN', label: 'processSettings.fields.apiToken', hint: 'n8nSetup.keyHint', advanced: false, secret: true },
  { name: 'PROCESS_N8N_WEBHOOK_BASE_URL', label: 'processSettings.fields.webhookBaseUrl', hint: 'n8nSetup.webhookHint', advanced: true, secret: false },
  { name: 'PROCESS_GALARIS_BASE_URL', label: 'processSettings.fields.galarisBaseUrl', hint: 'n8nSetup.galarisHint', advanced: true, secret: false },
  { name: 'PROCESS_N8N_WEBHOOK_AUTH_TOKEN', label: 'processSettings.fields.webhookAuthToken', hint: 'n8nSetup.secretHint', advanced: true, secret: true },
  { name: 'PROCESS_N8N_WEBHOOK_AUTH_HEADER', label: 'processSettings.fields.webhookAuthHeader', hint: 'n8nSetup.headerHint', advanced: true, secret: false },
  { name: 'PROCESS_N8N_CALLBACK_AUTH_HEADER', label: 'processSettings.fields.callbackAuthHeader', hint: 'n8nSetup.callbackHint', advanced: true, secret: false },
]
const form = reactive<Record<string, string>>(Object.fromEntries(fields.map(field => [field.name, ''])))
const clearedSecrets = reactive(new Set<string>())
const initialized = ref(false)
const loading = ref(true)
const loadError = ref(false)
const busy = ref(false)
const defaultGalarisUrl = ref('')
const result = ref<{ ok: boolean; message: string } | null>(null)
let generation = 0
const webhookUrl = computed(() => form.PROCESS_N8N_WEBHOOK_BASE_URL?.trim() || form.PROCESS_N8N_BASE_URL?.trim())
const galarisUrl = computed(() => form.PROCESS_GALARIS_BASE_URL?.trim() || defaultGalarisUrl.value)
function configured(name: string): boolean {
  return Boolean(params.getParamByName(name)?.secret && params.getParamByName(name)?.configured && !clearedSecrets.has(name))
}
watch(() => params.params, items => {
  if (initialized.value || !items.some(item => item.name === 'PROCESS_N8N_BASE_URL')) return
  for (const field of fields) form[field.name] = field.secret ? '' : (params.getParamValue(field.name) ?? '')
  initialized.value = true
}, { immediate: true, deep: true })
watch(form, () => { result.value = null }, { deep: true, flush: 'sync' })
watch(canEdit, () => { generation++; result.value = null })
onUnmounted(() => { generation++ })

async function loadDefaults(): Promise<void> {
  loading.value = true
  loadError.value = false
  try { defaultGalarisUrl.value = (await configurationService.defaults()).galaris_base_url }
  catch { loadError.value = true }
  finally { loading.value = false }
}
onMounted(loadDefaults)

function clearSecret(name: string): void {
  showConfirmationDialog({ title: t('configuration.clearSecretTitle'), message: t('configuration.clearSecretMessage'), cancel: true })
    .onOk(() => { form[name] = ''; clearedSecrets.add(name); result.value = null })
}
function generateSecret(): void {
  form.PROCESS_N8N_WEBHOOK_AUTH_TOKEN = Array.from(crypto.getRandomValues(new Uint8Array(32)), byte => byte.toString(16).padStart(2, '0')).join('')
  clearedSecrets.delete('PROCESS_N8N_WEBHOOK_AUTH_TOKEN')
}
async function copySecret(): Promise<void> {
  try { await copyToClipboard(form.PROCESS_N8N_WEBHOOK_AUTH_TOKEN ?? ''); $q.notify({ type: 'positive', message: t('n8nSetup.copied') }) }
  catch { $q.notify({ type: 'negative', message: t('n8nSetup.copyError') }) }
}
async function save(test: boolean): Promise<void> {
  if (!canEdit.value || busy.value || !initialized.value) return
  const current = ++generation
  busy.value = true
  result.value = null
  let saved = false
  try {
    for (const field of fields) {
      if (current !== generation || !canEdit.value) return
      const value = (form[field.name] ?? '').trim()
      const clear = field.secret && clearedSecrets.has(field.name) && !value
      if (field.secret ? !value && !clear : value === (params.getParamValue(field.name) ?? '')) continue
      await params.updateParam(field.name, clear ? null : value, clear)
      if (field.secret) { form[field.name] = ''; clearedSecrets.delete(field.name) }
      else form[field.name] = params.getParamValue(field.name) ?? ''
    }
    saved = true
    if (current !== generation || !canEdit.value) return
    if (!test) { result.value = { ok: true, message: t('configuration.saved') }; return }
    const response = await configurationService.test()
    if (current !== generation || !canEdit.value) return
    const key = `n8nSetup.errors.${response.code}`
    result.value = { ok: response.ok, message: response.ok ? response.message || t('n8nSetup.connected') : t(te(key) ? key : 'n8nSetup.errors.unknown') }
  } catch {
    if (current === generation) result.value = { ok: false, message: t(saved ? 'n8nSetup.testError' : 'n8nSetup.saveError') }
  } finally { busy.value = false }
}
</script>

<style scoped>
.n8n-settings { min-width: 0; overflow-wrap: anywhere; }
.n8n-fields { display: grid; gap: 20px; }
.n8n-fields > * { min-width: 0; }
.n8n-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.n8n-addresses { padding: 16px; background: var(--solaire-blue-light); border-radius: 8px; }
.n8n-status { background: var(--solaire-green-light); }
.n8n-status :deep(.q-banner__avatar) { color: var(--solaire-green-accent); }
.n8n-status--error { background: var(--solaire-red-light); }
.n8n-status--error :deep(.q-banner__avatar) { color: var(--solaire-red-accent); }
body.body--dark .n8n-addresses { background: var(--solaire-blue-dark); }
body.body--dark .n8n-status { background: var(--solaire-green-dark); }
body.body--dark .n8n-status--error { background: var(--solaire-red-dark); }
@media (min-width: 1024px) { .n8n-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
