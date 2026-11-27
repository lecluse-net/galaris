<template>
  <q-dialog v-model="open" :aria-labelledby="titleId">
    <q-card class="service-import-dialog galaris-dialog-card">
      <DialogHeader :title="t('services.importService')" :title-id="titleId" />

      <q-card-section v-if="conflict === null" class="galaris-dialog-body">
        <input ref="fileInput" type="file" accept=".yaml,.yml" hidden @change="onFileSelected" />
        <div class="import-dropzone column items-center justify-center q-gutter-y-sm q-pa-md"
             :class="{ 'import-dropzone--active': preview }" @dragover.prevent @drop.prevent="onFileDrop">
          <template v-if="preview">
            <q-icon name="check_circle" size="32px" color="positive" aria-hidden="true" />
            <div class="text-body1 text-weight-bold">{{ preview.code }}</div>
            <div class="text-caption">{{ preview.label }}</div>
          </template>
          <q-btn outline color="primary" icon="upload_file"
                 :label="t(preview ? 'services.changeFile' : 'services.dropYaml')"
                 :loading="reading" :disable="sendingThisFile" @click="fileInput?.click()" />
        </div>
      </q-card-section>

      <q-card-section v-else class="galaris-dialog-body">
        <q-banner class="bg-warning text-white q-mb-md" rounded>
          <template #avatar><q-icon name="warning" /></template>
          {{ t('services.overwriteTitle', { name: conflict }) }}
        </q-banner>
        <p class="text-body2">{{ t('services.overwriteText') }}</p>
      </q-card-section>

      <q-card-section v-if="error" role="alert" class="text-negative q-pt-none">
        {{ error }}
      </q-card-section>

      <q-card-actions align="right" class="galaris-dialog-actions">
        <q-btn outline color="primary" :label="t('common.cancel')" v-close-popup />
        <q-btn v-if="conflict !== null" outline color="primary" :label="t('services.changeFile')"
               :disable="sendingThisFile" @click="backToFile" />
        <q-btn v-if="canEdit" :color="conflict === null ? 'primary' : 'warning'"
               :label="t(conflict === null ? 'services.import' : 'services.replace')"
               :icon="conflict === null ? 'upload' : 'swap_horiz'"
               :loading="pendingSubmission !== null" :disable="reading || !yaml.trim()"
               @click="submit" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onScopeDispose, ref, useId, useTemplateRef, watch } from 'vue'
import { isAxiosError } from 'axios'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { sessionGeneration } from '@/core/api'
import { DialogHeader } from '@/core/util/facade'
import serviceApi from '../services/serviceApi'

const open = defineModel<boolean>({ required: true })
const { canEdit } = defineProps<{ canEdit: boolean }>()
const emit = defineEmits<{ imported: [code: string, reveal: boolean] }>()
const { t } = useI18n()
const $q = useQuasar()
const titleId = useId()
const fileInput = useTemplateRef<HTMLInputElement>('fileInput')

const yaml = ref('')
const preview = ref<{ code: string; label: string } | null>(null)
const conflict = ref<string | null>(null)
const error = ref('')
const reading = ref(false)
const dialogGeneration = ref(0)
const pendingSubmission = ref<number | null>(null)
const sendingThisFile = computed(() => pendingSubmission.value === dialogGeneration.value)
let fileRead = 0
let disposed = false

watch(open, () => {
  dialogGeneration.value++
  fileRead++
  yaml.value = ''
  preview.value = null
  conflict.value = null
  error.value = ''
  reading.value = false
}, { flush: 'sync' })

watch(() => canEdit, allowed => {
  if (!allowed) open.value = false
}, { flush: 'sync' })

onScopeDispose(() => {
  disposed = true
  fileRead++
})

async function readFile(file: File): Promise<void> {
  if (!open.value || !canEdit || sendingThisFile.value) return
  const request = ++fileRead
  reading.value = true
  yaml.value = ''
  preview.value = null
  error.value = ''
  try {
    const content = await file.text()
    if (request !== fileRead) return
    yaml.value = content
    // The preview is advisory. The API validates the full YAML.
    const code = content.match(/^code\s*:\s*(.+)$/m)?.[1]?.trim()
    const label = content.match(/^label\s*:\s*(.+)$/m)?.[1]?.trim()
    if (code && label) preview.value = { code, label }
    else error.value = t('services.detectError')
  } catch {
    if (request === fileRead) error.value = t('services.importError')
  } finally {
    if (request === fileRead) reading.value = false
  }
}

function onFileSelected(event: Event): void {
  if (!(event.target instanceof HTMLInputElement)) return
  const file = event.target.files?.[0]
  if (file) void readFile(file)
  event.target.value = ''
}

function onFileDrop(event: DragEvent): void {
  const file = event.dataTransfer?.files[0]
  if (file) void readFile(file)
}

function backToFile(): void {
  conflict.value = null
  error.value = ''
}

async function submit(): Promise<void> {
  if (!open.value || !canEdit || reading.value || pendingSubmission.value !== null || !yaml.value.trim()) return
  const generation = dialogGeneration.value
  const session = sessionGeneration()
  const activeSession = () => !disposed && session === sessionGeneration()
  const current = () => activeSession() && open.value && dialogGeneration.value === generation
  const overwrite = conflict.value !== null
  pendingSubmission.value = generation
  error.value = ''
  try {
    const { data } = await serviceApi.importService(yaml.value, overwrite)
    if (!activeSession()) return
    const reveal = current()
    if (reveal) open.value = false
    $q.notify({
      type: 'positive',
      message: t(data.created ? 'services.savedCreated' : 'services.savedUpdated', { code: data.code }),
    })
    emit('imported', data.code, reveal)
  } catch (cause) {
    if (!current()) return
    const response = isAxiosError<{ detail?: unknown }>(cause) ? cause.response : undefined
    const detail = typeof response?.data?.detail === 'string' ? response.data.detail : ''
    if (response?.status === 409 && !overwrite) {
      conflict.value = detail.match(/'([^']+)'/)?.[1] ?? preview.value?.code ?? '?'
    } else {
      error.value = detail || t('services.importError')
    }
  } finally {
    pendingSubmission.value = null
  }
}
</script>

<style scoped>
.service-import-dialog { width: 100%; max-width: 600px; }
.import-dropzone {
  border: 2px dashed color-mix(in srgb, currentColor 28%, transparent);
  border-radius: 8px;
  min-height: 160px;
  overflow-wrap: anywhere;
}
.import-dropzone:hover { border-color: var(--q-primary); }
.import-dropzone--active { border-color: var(--q-positive); }
</style>
