<template>
  <q-dialog v-model="open">
    <q-card class="galaris-dialog-card" style="width: 960px; max-width: 96vw">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6">{{ t('documents.formatCatalogue.title') }}</div><q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <q-card-section>
        <p>{{ t('documents.formatCatalogue.description') }}</p>
        <div v-if="loading" role="status"><q-spinner color="primary" /> {{ t('documents.loading') }}</div>
        <q-banner v-else-if="error" role="alert">
          {{ t('documents.formatCatalogue.error') }}
          <template #action><q-btn outline color="primary" :label="t('documents.retry')" @click="load" /></template>
        </q-banner>
        <div v-else-if="!documentFormatCatalogue.length">{{ t('documents.formatCatalogue.empty') }}</div>
        <div v-else class="scroll">
          <q-markup-table flat bordered wrap-cells>
            <thead><tr><th>{{ t('documents.documentFormat') }}</th><th>{{ t('documents.formatCatalogue.provider') }}</th><th v-for="capability in capabilities" :key="capability">{{ t(`documents.formatCatalogue.${capability}`) }}</th></tr></thead>
            <tbody><tr v-for="format in documentFormatCatalogue" :key="format.code">
              <td><q-icon :name="format.icon" color="primary" /> {{ formatLabel(format.code) }}<div class="text-caption">{{ format.code }} · {{ format.version }}</div></td>
              <td>{{ format.provider }}</td>
              <td v-for="capability in capabilities" :key="capability">{{ t(`documents.formatCatalogue.${support(format, capability)}`) }}</td>
            </tr></tbody>
          </q-markup-table>
        </div>
        <p class="text-caption q-mt-md">{{ t('documents.formatCatalogue.qualification') }}</p>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { documentFormatCatalogue, findDocumentFormat } from '../documentFormats'
import type { DocumentFormatDescriptor, FormatCapability } from '../formatRegistry'
import { documentService } from '../services/documentService'
const open = defineModel<boolean>({ required: true })
const { t } = useI18n()
const loading = ref(false), error = ref(false)
const capabilities: FormatCapability[] = ['editor', 'preview', 'embed', 'thumbnail', 'pdf', 'native_export', 'import']
let controller: AbortController | undefined
function formatLabel(code: string): string { const contribution = findDocumentFormat(code); return contribution ? t(contribution.label) : code }
function support(format: DocumentFormatDescriptor, capability: FormatCapability): string {
  const contribution = findDocumentFormat(format.code, format.version)
  if (capability === 'editor' && !contribution) return 'unavailable'
  if (capability === 'preview' && !contribution?.preview) return 'fallback'
  if (capability === 'embed' && !contribution?.embed) return 'fallback'
  return format.capabilities[capability]
}
async function load(): Promise<void> {
  controller?.abort()
  const request = new AbortController(); controller = request
  loading.value = true; error.value = false
  try { await documentService.formats(request.signal) }
  catch { if (!request.signal.aborted) error.value = true }
  finally { if (controller === request) loading.value = false }
}
watch(open, value => { if (value) void load(); else controller?.abort() }, { immediate: true })
onBeforeUnmount(() => controller?.abort())
</script>
