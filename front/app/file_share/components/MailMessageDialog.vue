<template>
  <ConversationTurnDialog :model-value="true" :title="message?.subject || title || t('files.mail.noSubject')" :aria-label="message?.subject || title || t('files.mail.noSubject')" icon="mail"
    :close-label="t('common.close')" :no-esc-dismiss="attachmentPreviewOpen" :allow-focus-outside="attachmentPreviewOpen" @update:model-value="!$event && emit('close')">
    <div v-if="loading && !message" class="q-pa-xl text-center" role="status"><q-spinner color="primary" size="32px" :aria-label="t('files.loading')" /></div>
    <div v-if="message" class="q-pa-md">
      <dl class="mail-headers">
        <dt>{{ t('files.mail.from') }}</dt><dd>{{ message.from_name }} &lt;{{ message.from_address }}&gt;</dd>
        <dt>{{ t('files.mail.to') }}</dt><dd>{{ message.to_addresses.join(', ') }}</dd>
        <template v-if="message.cc_addresses.length"><dt>{{ t('files.mail.cc') }}</dt><dd>{{ message.cc_addresses.join(', ') }}</dd></template>
        <template v-if="message.date"><dt>{{ t('files.mail.date') }}</dt><dd>{{ formatDate(message.date) }}</dd></template>
      </dl>
      <q-separator class="q-my-md" />
      <div class="mail-body">{{ body || t('files.mail.emptyBody') }}</div>
      <q-btn v-if="message.next_body_offset !== null" class="q-mt-md" outline color="primary" :label="t('files.mail.more')" :loading="loading" @click="load(true)" />
      <ResourceAttachments v-if="message.attachments.length" class="q-mt-lg" :resource-id="reference" :agent-id="agentId"
        :attachments="attachments" :resource-source="source" @previewing="attachmentPreviewOpen = $event" />
    </div>
    <q-banner v-if="error" class="q-ma-md" role="alert">
      {{ t('files.mail.loadError') }}
      <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="load(message !== null)" /></template>
    </q-banner>
  </ConversationTurnDialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ConversationTurnDialog, ResourceAttachments, type AttachmentSource } from '@/core/util'
import { mailBrowserService, type MailMessage } from '../services/mailBrowserService'
import { fileBrowserService } from '../services/fileBrowserService'

const { agentId, reference, title = '' } = defineProps<{ agentId: number; reference: string; title?: string }>()
const emit = defineEmits<{ close: [] }>()
const { t, locale } = useI18n()
const message = ref<MailMessage | null>(null)
const body = ref(''), loading = ref(false), error = ref(false)
const attachmentPreviewOpen = ref(false)
let request: AbortController | undefined
function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(date) : value
}
const attachments = computed(() => message.value?.attachments.map(item => ({ id: item.uri, uri: item.uri, name: item.filename, media_type: item.media_type, size_bytes: item.size })) ?? [])
const source: AttachmentSource = {
  content: (item, preview, signal) => fileBrowserService.content(agentId, item.id, preview, signal),
  videoUrl: item => fileBrowserService.videoUrl(agentId, item.id),
  releaseVideoUrl: fileBrowserService.releaseVideoUrl,
}
async function load(more = false): Promise<void> {
  request?.abort()
  const current = new AbortController(); request = current
  loading.value = true; error.value = false
  try {
    const offset = more ? message.value?.next_body_offset ?? 0 : 0
    const result = await mailBrowserService.message(agentId, reference, offset, current.signal)
    if (current.signal.aborted) return
    if (result.ref !== reference || result.body_start !== offset || (result.next_body_offset !== null && result.next_body_offset <= offset)) throw new Error('Invalid Mail body page')
    body.value = more ? body.value + result.body : result.body
    message.value = result
  } catch { if (!current.signal.aborted) error.value = true }
  finally { if (!current.signal.aborted) loading.value = false }
}
watch([() => agentId, () => reference], () => { message.value = null; body.value = ''; void load() }, { immediate: true })
onBeforeUnmount(() => request?.abort())
</script>

<style scoped>
.mail-headers { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 6px 16px; margin: 0; }
.mail-headers dt { font-weight: 600; }
.mail-headers dd { margin: 0; overflow-wrap: anywhere; }
.mail-body { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
