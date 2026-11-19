<template>
  <ResourcePicker v-model="adding" :agent-id="agentId" :busy="busy" :error="error" @select="select" @hide="finishPicker" />
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { richLinkCard, richLinkDefaultMode, richLinkHasCard, validRichLink } from '@/core/util/richText'
import { attachmentReference, documentResourceHtml } from '@/core/util'
import { resourceBlock, resourceLinkElement } from '@/core/util/facade'
import { resourceTarget, type FileEntry } from '@/app/file_share/interface'
import ResourcePicker from './resourcePicker.vue'

const { documentId, agentId, editable, resourcesOnly = false, host = 'text' } = defineProps<{
  documentId?: string; agentId: number | null; editable: boolean; resourcesOnly?: boolean; host?: 'text' | 'mindmap'
}>()
const adding = defineModel<boolean>('pickerOpen', { default: false })
const emit = defineEmits<{ picked: [html: string]; 'resources-picked': [resources: { uri: string; name: string }[]] }>()
const { t } = useI18n()
const error = ref(''), busy = ref(false)
let generation = 0
async function reference(entry: FileEntry, selectedAgent: number): Promise<string> {
  const title = String(entry.metadata?.label ?? entry.name)
  const image = !entry.is_collection && /^image\/(png|jpeg|webp|gif)$/.test(entry.media_type)
  if (attachmentReference(entry.uri)) return documentResourceHtml({ uri: entry.uri, name: title, size: entry.size ?? 0, mediaType: entry.media_type })
  let href = entry.uri
  if (image || !validRichLink(href)) {
    // Existing provider files stay at their source; only explicit uploads create attachments.
    const target = new URL('/files', window.location.origin)
    target.searchParams.set('agent_id', String(selectedAgent))
    target.searchParams.set('uri', entry.uri)
    href = target.href
  }
  if (image) {
    const block = resourceBlock(href, title, 'embed')
    block.classList.add('image')
    return block.outerHTML
  }
  if (richLinkDefaultMode(entry.uri, host) === 'card') {
    if (['process', 'process_run'].includes(resourceTarget(entry, selectedAgent)?.kind ?? '')) return resourceBlock(href, title, 'card').outerHTML
    if (richLinkHasCard(entry.uri)) {
      const html = await richLinkCard(entry.uri, selectedAgent)
      const block = new DOMParser().parseFromString(html, 'text/html').querySelector<HTMLElement>('blockquote.galaris-link-card')
      if (block) { block.dataset.resourceMode = 'card'; return block.outerHTML }
    }
  }
  const link = resourceLinkElement(href, title)
  link.dataset.resourceMode = 'link'
  return `<p>${link.outerHTML}</p>`
}
async function select(entries: FileEntry[], selectedAgent: number): Promise<void> {
  if (!editable || busy.value) return
  if (resourcesOnly) {
    emit('resources-picked', entries.map(entry => ({ uri: entry.uri, name: String(entry.metadata?.label ?? entry.name) })))
    adding.value = false
    return
  }
  busy.value = true; error.value = ''
  const current = ++generation
  try {
    const html = await Promise.all(entries.map(entry => reference(entry, selectedAgent)))
    if (!editable || !adding.value || current !== generation) return
    emit('picked', html.join(''))
    adding.value = false
  } catch { if (current === generation) error.value = t('documents.internalAttachments.error') }
  finally { if (current === generation) busy.value = false }
}
function finishPicker(): void { generation++; busy.value = false; emit('picked', '') }
watch(adding, value => { generation++; busy.value = false; if (value) error.value = '' })
watch(() => [documentId, agentId], () => { finishPicker(); adding.value = false; error.value = '' })
onBeforeUnmount(finishPicker)
</script>
