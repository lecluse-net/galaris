<template>
  <ResourcePicker v-model="adding" references :agent-id="agentId" :busy="busy" :error="error" @select="select" @reference="selectReference" @hide="finishPicker" />
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { validRichLink, richLinkCard } from '@/core/util/richText'
import { documentFolderId } from '@/core/util'
import type { RichLinkTarget } from '@/core/util/richText'
import { processReferenceHtml } from '@/app/process/interface'
import { resourceTarget, type FileEntry } from '@/app/file_share/interface'
import ResourcePicker from './resourcePicker.vue'

const { documentId, agentId, editable, resourcesOnly = false } = defineProps<{ documentId?: string; agentId: number | null; editable: boolean; resourcesOnly?: boolean }>()
const adding = defineModel<boolean>('pickerOpen', { default: false })
const emit = defineEmits<{ picked: [html: string]; 'resources-picked': [resources: { uri: string; name: string }[]] }>()
const { t } = useI18n()
const error = ref(''), busy = ref(false)
let generation = 0
function selectReference(value: RichLinkTarget): void {
  if (!editable || busy.value || !validRichLink(value.uri)) return
  if (resourcesOnly) {
    emit('resources-picked', [{ uri: value.uri, name: value.title }]); adding.value = false
    return
  }
  const link = document.createElement('a'); link.href = value.uri; link.textContent = value.title
  emit('picked', `<p>${link.outerHTML}</p>`); adding.value = false
}

function reference(entry: FileEntry, selectedAgent: number): string {
  const title = String(entry.metadata?.label ?? entry.name)
  if (['process', 'process_run'].includes(resourceTarget(entry, selectedAgent)?.kind ?? '')) return processReferenceHtml(entry.uri, title, false)
  const anchor = document.createElement('a')
  if (validRichLink(entry.uri)) anchor.href = entry.uri
  else {
    // Existing provider files stay at their source; only explicit uploads create attachments.
    const target = new URL('/files', window.location.origin)
    target.searchParams.set('agent_id', String(selectedAgent))
    target.searchParams.set('uri', entry.uri)
    anchor.href = target.href
  }
  anchor.textContent = title
  return `<p>${anchor.outerHTML}</p>`
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
    const html = await Promise.all(entries.map(entry => documentFolderId(entry.uri) ? richLinkCard(entry.uri, null) : reference(entry, selectedAgent)))
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
