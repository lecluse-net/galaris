<template>
  <q-btn flat round dense icon="verified_user" :aria-label="t('documents.apps.permissions')" :disable="disabled" @click="open = true">
    <q-tooltip>{{ t('documents.apps.permissions') }}</q-tooltip>
  </q-btn>
  <q-dialog v-model="open">
    <q-card style="width: 700px; max-width: 95vw">
      <q-card-section class="galaris-dialog-title row items-center">
        <div class="text-h6">{{ t('documents.apps.permissions') }}</div>
        <q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <q-card-section>
        <p>{{ t('documents.apps.permissionsHint') }}</p>
        <q-spinner v-if="loading" />
        <div v-if="error" role="alert">{{ error }}</div>
        <q-btn v-if="error" flat :label="t('documents.retry')" @click="load" />
        <p v-if="permissions && !permissions.grants.length">{{ t('documents.apps.noDatasets') }}</p>
        <q-list v-if="permissions" separator>
          <q-item v-for="grant in permissions.grants" :key="grant.app_key + ':' + grant.alias">
            <q-item-section>
              <q-item-label>{{ grant.dataset_title ?? t('documents.apps.unavailableDataset') }}</q-item-label>
              <q-item-label caption>{{ grant.app_title }} · {{ grant.alias }}</q-item-label>
              <q-item-label caption class="text-break">document://{{ grant.dataset_id }}</q-item-label>
              <q-item-label caption>{{ t('documents.apps.requestedAccess') }}: {{ t('documents.apps.' + grant.requested_access) }}</q-item-label>
              <q-select :model-value="grant.access ?? 'none'" :options="options(grant)" emit-value map-options
                :label="t('documents.apps.allowedAccess')" :disable="saving || loading"
                @update:model-value="value => save(grant, value === 'none' ? null : value)" />
            </q-item-section>
          </q-item>
        </q-list>
      </q-card-section>
      <q-card-actions align="right"><q-btn v-close-popup flat :label="t('common.close')" /></q-card-actions>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { memoryService } from '../services/memoryService'
import type { AppGrant, AppPermissions } from '../documentApps'

const { documentId, revision, disabled = false, canWrite = false } = defineProps<{
  documentId: string; revision: number; disabled?: boolean; canWrite?: boolean
}>()
const { t } = useI18n()
const emit = defineEmits<{ changed: [] }>()
const open = ref(false), loading = ref(false), saving = ref(false), error = ref('')
const permissions = ref<AppPermissions | null>(null)
let controller = new AbortController()
function options(grant: AppGrant) {
  return ['none', 'read', ...(grant.requested_access === 'write' && canWrite ? ['write'] : [])].map(value => ({
    value, label: t('documents.apps.' + value),
  }))
}
async function load(): Promise<void> {
  controller.abort(); controller = new AbortController()
  const signal = controller.signal
  permissions.value = null; error.value = ''; loading.value = true; saving.value = false
  try {
    const result = await memoryService.appPermissions(documentId, signal)
    if (signal.aborted) return
    if (result.document_revision !== revision) throw new Error('revision')
    permissions.value = result
  } catch { if (!signal.aborted) error.value = t('documents.apps.permissionsError') }
  finally { if (!signal.aborted) loading.value = false }
}
async function save(grant: AppGrant, access: AppGrant['access']): Promise<void> {
  if (saving.value || !permissions.value) return
  const signal = controller.signal
  saving.value = true; error.value = ''
  try {
    const result = await memoryService.setAppPermission(documentId, permissions.value.document_revision, grant, access, signal)
    if (!signal.aborted) { permissions.value = result; emit('changed') }
  } catch { if (!signal.aborted) error.value = t('documents.apps.permissionsError') }
  finally { if (!signal.aborted) saving.value = false }
}
watch(open, value => { if (value) void load(); else controller.abort() })
watch(() => [documentId, revision, disabled], () => { controller.abort(); open.value = false; permissions.value = null })
onBeforeUnmount(() => controller.abort())
</script>
