<template>
  <q-dialog v-model="open" :maximized="$q.screen.lt.md" @hide="emit('hide')">
    <q-card class="internal-file-picker galaris-dialog-card column no-wrap">
      <q-toolbar class="galaris-dialog-title">
        <q-toolbar-title>{{ t('documents.internalAttachments.add') }}</q-toolbar-title>
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-toolbar>
      <q-tabs v-model="tab" dense align="left">
        <q-tab name="files" :label="t('richEditor.referenceFiles')" />
        <q-tab name="folders" :label="t('documents.collections.title')" />
        <q-tab v-if="references" name="objects" :label="t('richEditor.referenceObjects')" />
      </q-tabs>
      <BusinessReferencePicker v-if="tab === 'objects'" :busy="busy" @select="emit('reference', $event)" />
      <DocumentFolderCollection v-else-if="tab === 'folders'" class="col scroll" selection :inert="busy || undefined" @select="entry => emit('select', [entry], selectedAgent ?? 0)" />
      <template v-else>
      <div class="q-pa-sm">
        <AgentSelect v-model="selectedAgent" :options="agentOptions" :load-agents="false" outlined dense :label="t('agent.selectPlaceholder')" :loading="loadingAgents" :disable="busy" />
      </div>
      <q-banner v-if="agentError" role="alert">{{ t('files.agentError') }} <q-btn outline :label="t('common.retry')" @click="loadAgents" /></q-banner>
      <q-banner v-if="error" role="alert">{{ error }}</q-banner>
      <AgentFileBrowser v-if="selectedAgent !== null" :key="selectedAgent" v-model:selected="selected" :agent-id="selectedAgent" :inert="busy || undefined" selection @confirm="confirm" />
      <q-card-section v-else class="col">{{ t('files.chooseAgent') }}</q-card-section>
      <q-card-section class="q-py-sm picker-selection" :aria-label="t('files.selection')">
        <span>{{ t('files.selectedCount', { count: selected.length }) }}</span>
        <q-chip v-for="entry in selected" :key="entry.uri" removable :disable="busy" @remove="selected = selected.filter(value => value.uri !== entry.uri)">{{ entry.name }}</q-chip>
      </q-card-section>
      <q-card-actions align="right" class="galaris-dialog-actions">
        <q-btn v-close-popup outline :label="t('common.cancel')" />
        <q-btn color="primary" :label="t('files.selectFiles')" :disable="!selected.length || selectedAgent === null" :loading="busy" @click="confirm" />
      </q-card-actions>
      </template>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AgentSelect, getAgentSelection, type AgentSelectionOption } from '@/app/agent'
import { DocumentFolderCollection } from '@/app/document'
import { AgentFileBrowser, type FileEntry } from '@/app/file_share/interface'
import BusinessReferencePicker from './BusinessReferencePicker.vue'
import type { RichLinkTarget } from '@/core/util/richText'
const open = defineModel<boolean>({ default: false })
const { agentId = null, busy = false, error = '', references = false } = defineProps<{ agentId?: number | null; busy?: boolean; error?: string; references?: boolean }>()
const emit = defineEmits<{ select: [entries: FileEntry[], agentId: number]; reference: [value: RichLinkTarget]; hide: [] }>()
const tab = ref('files')
const { t } = useI18n()
const selectedAgent = ref<number | null>(agentId), selected = ref<FileEntry[]>([]), agents = ref<AgentSelectionOption[]>([])
const loadingAgents = ref(false), agentError = ref(false)
let request: AbortController | undefined
const agentOptions = computed(() => agents.value.map(agent => ({ value: agent.id, label: agent.label, hasAvatar: agent.has_avatar })))
async function loadAgents(): Promise<void> {
  request?.abort(); const controller = new AbortController(); request = controller
  loadingAgents.value = true; agentError.value = false
  try {
    const result = await getAgentSelection('management', controller.signal)
    if (controller.signal.aborted) return
    agents.value = result
    selectedAgent.value = result.some(agent => agent.id === agentId) ? agentId : result[0]?.id ?? null
  } catch { if (!controller.signal.aborted) agentError.value = true }
  finally { if (!controller.signal.aborted) loadingAgents.value = false }
}
function confirm(): void { if (!busy && selectedAgent.value !== null && selected.value.length) emit('select', selected.value, selectedAgent.value) }
watch(selectedAgent, () => { selected.value = [] })
watch(open, value => { selected.value = []; if (value) void loadAgents(); else request?.abort() }, { immediate: true })
onBeforeUnmount(() => request?.abort())
</script>
<style scoped>
.internal-file-picker { width: 1000px; max-width: 96vw; height: 740px; max-height: 92dvh; }
.picker-selection { max-height: 100px; overflow: auto; border-top: 1px solid var(--solaire-gray-accent); }
@media (max-width: 1023px) { .internal-file-picker { width: 100%; max-width: 100%; height: 100%; max-height: 100%; } }
</style>
