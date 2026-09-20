<template>
  <section :aria-label="t('harnesses.setup.title')">
    <q-spinner v-if="loading" />
    <q-banner v-else-if="loadFailed" class="q-mb-md">
      {{ t('harnesses.manager.loadFailed') }}
      <q-btn flat :label="t('common.retry')" @click="load" />
    </q-banner>
    <template v-else-if="saved">
      <q-form @submit="save" class="q-gutter-y-sm">
        <div class="manager-config__fields">
          <q-input dense hide-bottom-space hide-hint v-model="form.manager_url" outlined :readonly="!canEdit || busy" :label="t('harnesses.setup.url')" :hint="t('harnesses.setup.urlHint')" />
          <q-input dense hide-bottom-space hide-hint v-model="form.galaris_api_url" outlined :readonly="!canEdit || busy" :label="t('harnesses.setup.api')" :hint="t('harnesses.setup.apiHint')" />
          <q-input dense hide-bottom-space hide-hint v-if="canEdit" v-model="secret" outlined type="password" autocomplete="new-password" :disable="busy" :label="t('harnesses.setup.secret')" :hint="t(saved.secret_configured ? 'harnesses.setup.keepSecret' : 'harnesses.setup.newSecret')">
            <template #append><q-icon v-if="saved.secret_configured" name="lock" size="18px"><q-tooltip>{{ t('harnesses.setup.keepSecret') }}</q-tooltip></q-icon></template>
          </q-input>
        </div>
        <div v-if="canEdit" class="row items-center q-gutter-sm">
          <q-btn v-if="!saved.secret_configured" flat no-caps :label="t('harnesses.setup.generate')" :disable="busy" @click="generate" />
          <q-btn unelevated no-caps color="primary" type="submit" :label="t('harnesses.setup.save')" :loading="saving" :disable="busy && !saving" />
          <q-btn flat no-caps icon="folder_zip" :label="t('harnesses.preferences.prepareInstallation')" @click="installationOpen = true" />
        </div>
        <div v-if="saved.secret_configured && secret" class="text-caption">{{ t('harnesses.setup.rotation') }}</div>
      </q-form>
      <q-dialog v-if="canEdit" v-model="installationOpen">
        <q-card class="manager-config__dialog">
          <q-card-section class="galaris-dialog-title row items-center no-wrap">
            <div class="text-h6">{{ t('harnesses.preferences.prepareInstallation') }}</div>
            <q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
          </q-card-section>
          <q-card-section>
        <p class="text-body2 q-mt-none">{{ t('harnesses.setup.exportHint') }}</p>
        <q-form class="q-gutter-y-md" @submit="exportEnv">
          <div class="row q-col-gutter-md">
            <q-input hide-bottom-space v-model="host.api_host" class="col-12 col-md-6" outlined :label="t('harnesses.setup.host')" :hint="t('harnesses.setup.hostHint')" />
            <q-input hide-bottom-space v-model.number="host.api_port" class="col-12 col-md-6" outlined type="number" min="1" max="65535" :label="t('harnesses.setup.port')" :hint="t('harnesses.setup.portHint')" />
          </div>
          <q-input hide-bottom-space v-model="host.allowed_ip" outlined :label="t('harnesses.setup.allowedIp')" :hint="t('harnesses.setup.allowedIpHint')" />
          <q-input hide-bottom-space v-model="host.base_dir" outlined :label="t('harnesses.setup.directory')" :hint="t('harnesses.setup.directoryHint')" />
          <q-input hide-bottom-space v-model="host.update_url" outlined :label="t('harnesses.release.updateUrl')" :hint="t('harnesses.release.updateUrlHint')" />
          <q-expansion-item :label="t('harnesses.setup.advanced')">
            <div class="q-gutter-y-md q-py-md">
              <q-input hide-bottom-space v-model="host.ignore_dirs" outlined :label="t('harnesses.setup.ignore')" />
              <q-input hide-bottom-space v-model.number="host.max_file_size_mb" outlined type="number" min="1" :max="sizeInMegabytes(1024, 'mebibytes')" step="1" :label="t('harnesses.setup.textLimit')" />
              <q-input hide-bottom-space v-model.number="host.max_raw_file_size_mb" outlined type="number" min="1" :max="sizeInMegabytes(10240, 'mebibytes')" step="1" :label="t('harnesses.setup.binaryLimit')" />
            </div>
          </q-expansion-item>
          <div v-if="dirty" role="status">{{ t('harnesses.setup.saveFirst') }}</div>
          <div class="row q-gutter-sm">
            <q-btn unelevated no-caps color="primary" icon="folder_zip" :label="t('harnesses.release.installationZip')" :disable="busy || dirty || !saved.secret_configured" :loading="packaging" @click="downloadInstallation" />
            <q-btn flat no-caps type="submit" :label="t('harnesses.setup.export')" :disable="busy || dirty || !saved.secret_configured" :loading="exporting" />
          </div>
          <p class="text-caption">{{ t('harnesses.release.privateZip') }}</p>
        </q-form>
        <div v-if="environment" class="q-mt-md">
          <p>{{ t('harnesses.setup.privateFile') }}</p>
          <pre class="manager-config__env">{{ environment }}</pre>
          <div class="row q-gutter-sm">
            <q-btn flat icon="content_copy" :label="t('harnesses.setup.copy')" @click="copy" />
            <q-btn flat icon="download" :label="t('harnesses.setup.download')" @click="download" />
            <q-btn flat :label="t('harnesses.setup.hide')" @click="environment = ''" />
          </div>
          <p class="q-mt-md">{{ t('harnesses.setup.install') }}</p>
          <pre class="manager-config__env">chmod 600 .env
make install
make service-install
make service-status
make service-logs</pre>
          <p>{{ t('harnesses.setup.existing') }}</p>
        </div>
        <div v-if="error" role="alert" class="q-mt-md">{{ error }}</div>
          </q-card-section>
          <q-card-actions align="right"><q-btn v-close-popup flat :label="t('common.close')" /></q-card-actions>
        </q-card>
      </q-dialog>
    </template>
    <div v-if="error && !installationOpen" role="alert" class="q-mt-md">{{ error }}</div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { copyToClipboard, exportFile, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { sizeInMegabytes, sizeFromMegabytes } from '@/core/util'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { managerService, type ManagerConfiguration, type ManagerHostSetup } from '../services/managerService'

const emit = defineEmits<{ saved: [] }>()
const { t } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.PARAMS_EDIT))
const saved = ref<ManagerConfiguration | null>(null)
const form = reactive({ manager_url: '', galaris_api_url: '' })
const secret = ref('')
const loading = ref(false)
const loadFailed = ref(false)
const saving = ref(false)
const generating = ref(false)
const exporting = ref(false)
const packaging = ref(false)
const busy = computed(() => saving.value || generating.value || exporting.value || packaging.value)
const error = ref('')
const environment = ref('')
const installationOpen = ref(false)
const host = reactive<ManagerHostSetup>({ api_host: '0.0.0.0', api_port: 8485, allowed_ip: '', base_dir: '/opt/galaris-harnesses', ignore_dirs: '', max_file_size_mb: 1, max_raw_file_size_mb: 512, update_url: '' })

function hostPayload(): ManagerHostSetup {
  return {
    ...host,
    max_file_size_mb: sizeFromMegabytes(host.max_file_size_mb, 'mebibytes'),
    max_raw_file_size_mb: sizeFromMegabytes(host.max_raw_file_size_mb, 'mebibytes'),
  }
}
const dirty = computed(() => !saved.value || secret.value !== '' || form.manager_url !== saved.value.manager_url || form.galaris_api_url !== saved.value.galaris_api_url)
let disposed = false
let revision = 0
watch([form, host, secret, canEdit], () => {
  revision++
  environment.value = ''
  if (!canEdit.value) { secret.value = ''; installationOpen.value = false }
}, { flush: 'sync' })
watch(installationOpen, () => { revision++; environment.value = ''; error.value = '' }, { flush: 'sync' })

async function load(): Promise<void> {
  if (loading.value) return
  loading.value = true
  loadFailed.value = false
  try {
    const data = await managerService.configuration()
    if (disposed) return
    saved.value = data
    Object.assign(form, { manager_url: data.manager_url, galaris_api_url: data.galaris_api_url })
  } catch { if (!disposed) loadFailed.value = true }
  finally { if (!disposed) loading.value = false }
}
async function generate(): Promise<void> {
  if (!canEdit.value || busy.value || saved.value?.secret_configured) return
  generating.value = true
  error.value = ''
  try {
    const value = await managerService.generateSecret()
    if (!disposed && canEdit.value) secret.value = value
  } catch { if (!disposed) error.value = t('harnesses.setup.error') }
  finally { if (!disposed) generating.value = false }
}
async function save(): Promise<void> {
  if (!canEdit.value || busy.value) return
  saving.value = true
  error.value = ''
  environment.value = ''
  try {
    const data = await managerService.save({ ...form, ...(secret.value ? { secret: secret.value } : {}) })
    if (disposed) return
    saved.value = data
    Object.assign(form, { manager_url: data.manager_url, galaris_api_url: data.galaris_api_url })
    secret.value = ''
    $q.notify({ type: 'positive', message: t('harnesses.setup.saved') })
    emit('saved')
  } catch { if (!disposed) error.value = t('harnesses.setup.error') }
  finally { if (!disposed) saving.value = false }
}
async function exportEnv(): Promise<void> {
  if (!canEdit.value || busy.value || dirty.value) return
  exporting.value = true
  error.value = ''
  const started = revision
  try {
    const value = await managerService.environment(hostPayload())
    if (!disposed && canEdit.value && started === revision) environment.value = value
  } catch { if (!disposed && started === revision) error.value = t('harnesses.setup.exportError') }
  finally { if (!disposed) exporting.value = false }
}
async function copy(): Promise<void> {
  try {
    await copyToClipboard(environment.value)
    $q.notify({ type: 'positive', message: t('harnesses.setup.copied') })
  } catch { error.value = t('harnesses.setup.copyError') }
}
async function downloadInstallation(): Promise<void> {
  if (!canEdit.value || busy.value || dirty.value || !saved.value?.secret_configured) return
  packaging.value = true
  error.value = ''
  const started = revision
  try {
    const archive = await managerService.installation(hostPayload())
    if (disposed || !canEdit.value || started !== revision) return
    if (exportFile('harness-manager-installation.zip', archive, 'application/zip') !== true) {
      error.value = t('harnesses.setup.copyError')
    }
  } catch { if (!disposed && started === revision) error.value = t('harnesses.release.downloadError') }
  finally { if (!disposed) packaging.value = false }
}
function download(): void {
  if (exportFile('harness-manager.env', environment.value, 'text/plain') !== true) error.value = t('harnesses.setup.copyError')
}
onMounted(load)
onUnmounted(() => { disposed = true; environment.value = ''; secret.value = '' })
</script>

<style scoped>
:deep(.q-field__messages) { line-height: 1.35; }
.manager-config__fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.manager-config__dialog { width: 760px; max-width: 94vw; }
@media (max-width: 1023px) { .manager-config__fields { grid-template-columns: minmax(0, 1fr); } }
.manager-config__env { white-space: pre-wrap; overflow-wrap: anywhere; padding: 16px; border-radius: 8px; background: var(--solaire-gray-light); }
.body--dark .manager-config__env { background: var(--solaire-gray-dark); }
</style>
