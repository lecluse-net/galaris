<template>
  <ResourcePicker v-model="adding" :agent-id="agentId" :busy="busy" :error="error" @select="select" @hide="finishPicker" />
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { validRichLink } from '@/core/util/richText'
import { processReferenceHtml } from '@/app/process/interface'
import { resourceTarget, type FileEntry } from '@/app/file_share/interface'
import ResourcePicker from './resourcePicker.vue'

const { documentId, agentId, editable } = defineProps<{ documentId: string; agentId: number | null; editable: boolean }>()
const adding = defineModel<boolean>('pickerOpen', { default: false })
const emit = defineEmits<{ picked: [html: string] }>()
const { t } = useI18n()
const error = ref(''), busy = ref(false)

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
function select(entries: FileEntry[], selectedAgent: number): void {
  if (!editable || busy.value) return
  busy.value = true; error.value = ''
  try {
    emit('picked', entries.map(entry => reference(entry, selectedAgent)).join(''))
    adding.value = false
  } catch { error.value = t('documents.internalAttachments.error') }
  finally { busy.value = false }
}
function finishPicker(): void { emit('picked', '') }
watch(adding, value => { if (value) error.value = '' })
watch(() => [documentId, agentId], () => { finishPicker(); adding.value = false; error.value = '' })
onBeforeUnmount(finishPicker)
</script>
