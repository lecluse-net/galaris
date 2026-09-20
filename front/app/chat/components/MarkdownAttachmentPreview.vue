<template>
  <div
    class="markdown-attachment-reader"
    role="document"
    :aria-label="t('chat.markdownPreview', { name: file.name })"
  >
    <div v-if="loading" class="markdown-attachment-state" role="status">
      <q-spinner color="primary" size="28px" />
      <span>{{ t('chat.loadingAttachmentPreview', { name: file.name }) }}</span>
    </div>
    <div v-else-if="failed" class="markdown-attachment-state text-negative" role="alert">
      <q-icon name="error_outline" size="24px" />
      <span>{{ t('chat.attachmentPreviewError', { name: file.name }) }}</span>
      <q-btn
        flat
        dense
        no-caps
        color="primary"
        icon="refresh"
        :label="t('chat.retryAttachmentPreview', { name: file.name })"
        @click="load"
      />
    </div>
    <Markdown v-else :content="content" />
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Markdown } from '@/core/util'
import type { MessengerFile } from '../types'
import { chatService } from '../services/chatService'

const props = withDefaults(defineProps<{
  roomId: string
  file: MessengerFile
  viewerAgentId?: number | null
}>(), {
  viewerAgentId: null,
})

const emit = defineEmits<{
  loaded: [fileId: string, content: string]
}>()

const { t } = useI18n()
const content = ref('')
const loading = ref(false)
const failed = ref(false)
let generation = 0

async function load(): Promise<void> {
  const currentGeneration = ++generation
  loading.value = true
  failed.value = false

  try {
    const blob = await chatService.attachmentBlob(
      props.roomId,
      props.file.id,
      props.viewerAgentId,
    )
    const text = await blob.text()
    if (currentGeneration !== generation) return

    content.value = text
    emit('loaded', props.file.id, text)
  } catch {
    if (currentGeneration === generation) failed.value = true
  } finally {
    if (currentGeneration === generation) loading.value = false
  }
}

watch(
  () => [props.roomId, props.file.id, props.viewerAgentId] as const,
  () => { void load() },
  { immediate: true },
)

onBeforeUnmount(() => { generation += 1 })
</script>

<style scoped>
.markdown-attachment-reader {
  box-sizing: border-box;
  width: 100%;
  height: min(520px, 62vh);
  min-height: 320px;
  padding: 18px 22px;
  overflow: auto;
  color: var(--chat-text, #20242c);
  background: var(--chat-surface-raised, #fff);
  border: 1px solid var(--chat-border, rgba(53, 69, 94, .14));
  border-radius: 8px;
}

.markdown-attachment-state {
  display: flex;
  min-height: 280px;
  align-items: center;
  justify-content: center;
  gap: 10px;
  flex-direction: column;
  text-align: center;
}

.markdown-attachment-reader :deep(.markdown-content img) {
  display: block;
  width: auto;
  max-width: 100%;
  height: auto;
  object-fit: contain;
}
</style>
