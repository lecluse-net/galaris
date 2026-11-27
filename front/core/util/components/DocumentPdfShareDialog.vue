<template>
  <q-dialog v-model="open" :aria-label="t('richEditor.share.title')">
    <q-card class="galaris-dialog-card" style="width: 420px; max-width: 95vw">
      <DialogHeader :title="t('richEditor.share.title')" :close-label="t('common.close')" />
      <q-card-section class="galaris-dialog-body">
        <div v-if="preparing" role="status"><q-spinner />{{ t('richEditor.share.preparing') }}</div>
        <div v-else-if="errorMessage" role="alert">{{ errorMessage }}</div>
        <div v-else-if="file">{{ file.name }}</div>
      </q-card-section>
      <q-card-actions align="right" class="galaris-dialog-actions">
        <q-btn color="primary" v-close-popup outline :label="t('common.cancel')" />
        <q-btn v-if="errorMessage && !file" color="primary" outline :label="t('common.retry')" @click="prepare" />
        <q-btn v-else color="primary" :disable="!file" :loading="sharing"
          :label="t(nativeShareData ? 'richEditor.share.action' : 'richEditor.share.save')" @click="share" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { saveBlobAsResource } from '../resourceViewer'
import DialogHeader from './DialogHeader.vue'

const { title, url, createFile } = defineProps<{ title?: string; url?: string; createFile: (signal: AbortSignal) => Promise<File> }>()
const open = defineModel<boolean>({ required: true })
const { t } = useI18n()
const preparing = ref(false), sharing = ref(false), errorMessage = ref('')
const file = shallowRef<File | null>(null)
let request: AbortController | undefined

const nativeShareData = computed<ShareData | null>(() => {
  if (!file.value || !navigator.share || !navigator.canShare) return null
  const files = [file.value]
  const options = [{ files, title, url }, { files, title, text: url }, { files }]
  return options.find(data => navigator.canShare(data)) ?? null
})

function reset(): void {
  request?.abort()
  request = undefined
  file.value = null
  errorMessage.value = ''
  preparing.value = false
  sharing.value = false
}

async function prepare(): Promise<void> {
  reset()
  const pending = new AbortController()
  request = pending
  preparing.value = true
  try {
    const next = await createFile(pending.signal)
    if (!pending.signal.aborted) file.value = next
  } catch {
    if (!pending.signal.aborted) errorMessage.value = t('richEditor.exportPdfFailed')
  } finally {
    if (request === pending) preparing.value = false
  }
}

async function share(): Promise<void> {
  const current = file.value
  if (!current || sharing.value) return
  sharing.value = true
  errorMessage.value = ''
  try {
    if (nativeShareData.value) await navigator.share(nativeShareData.value)
    else saveBlobAsResource(current, current.name)
    if (file.value === current) open.value = false
  } catch (error) {
    if (file.value === current && !(error instanceof DOMException && error.name === 'AbortError')) errorMessage.value = t('richEditor.share.failed')
  } finally {
    if (file.value === current) sharing.value = false
  }
}

watch(open, value => { if (value) void prepare(); else reset() }, { flush: 'sync', immediate: true })
onBeforeUnmount(reset)
</script>
