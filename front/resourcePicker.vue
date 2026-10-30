<template>
  <q-dialog v-model="open" :maximized="$q.screen.lt.md" :allow-focus-outside="previewing" :no-esc-dismiss="previewing" @hide="emit('hide')">
    <q-card class="internal-file-picker galaris-dialog-card column no-wrap">
      <q-toolbar class="galaris-dialog-title">
        <q-toolbar-title>{{ title || t('documents.internalAttachments.add') }}</q-toolbar-title>
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-toolbar>
      <div class="picker-toolbar">
        <AgentSelect v-model="selectedAgent" class="picker-agent" :options="agentOptions" :load-agents="false" outlined dense :label="t('agent.selectPlaceholder')" :loading="loadingAgents" :disable="busy" />
        <div class="picker-search">
          <q-input v-model="query" class="col" dense outlined clearable debounce="250" :disable="!browser?.canSearch || busy" :label="t('files.searchLocation')">
            <template #prepend><q-icon name="search" /></template>
          </q-input>
          <q-btn flat round dense color="primary" icon="refresh" :aria-label="t('files.refresh')" :disable="!browser?.canSearch || busy" :loading="browser?.refreshing" @click="browser?.refresh()">
            <q-tooltip>{{ t('files.refresh') }}</q-tooltip>
          </q-btn>
        </div>
      </div>
      <q-banner v-if="agentError" role="alert">{{ t('files.agentError') }} <q-btn outline :label="t('common.retry')" @click="loadAgents" /></q-banner>
      <q-banner v-if="error" role="alert">{{ error }}</q-banner>
      <AgentFileBrowser v-if="selectedAgent !== null" ref="browser" :key="selectedAgent" v-model:selected="selected" v-model:query="query" :agent-id="selectedAgent" :inert="busy || undefined" selection external-controls @confirm="confirm" @previewing="previewing = $event" />
      <q-card-section v-else class="col">{{ t('files.chooseAgent') }}</q-card-section>
      <footer class="picker-footer galaris-dialog-actions">
      <q-separator />
      <div class="picker-footer-content">
      <div class="picker-selection" :aria-label="t('files.selection')">
        <div class="text-caption text-weight-medium">{{ t('files.selectedCount', { count: selected.length }) }}</div>
        <div class="picker-selected-items">
          <q-chip v-for="entry in selected" :key="entry.uri" removable :disable="busy" @remove="selected = selected.filter(value => value.uri !== entry.uri)"><span class="ellipsis">{{ executionResourceLabel(entry, locale) ?? entry.name }}</span><q-tooltip>{{ entry.uri }}</q-tooltip></q-chip>
        </div>
      </div>
      <q-card-actions align="right" class="galaris-dialog-actions q-pa-none">
        <q-btn v-close-popup outline color="primary" :label="t('common.cancel')" />
        <q-btn color="primary" :label="t('files.selectFiles')" :disable="!validSelection || selectedAgent === null" :loading="busy" @click="confirm" />
      </q-card-actions>
      </div>
      </footer>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AgentSelect, getAgentSelection, type AgentSelectionOption } from '@/app/agent'
import { AgentFileBrowser, executionResourceLabel, type FileEntry } from '@/app/file_share/interface'
const open = defineModel<boolean>({ default: false })
const { agentId = null, busy = false, error = '', title = '', single = false } = defineProps<{ agentId?: number | null; busy?: boolean; error?: string; title?: string; single?: boolean }>()
const emit = defineEmits<{ select: [entries: FileEntry[], agentId: number]; hide: [] }>()
const { t, locale } = useI18n()
const selectedAgent = ref<number | null>(agentId), selected = ref<FileEntry[]>([]), agents = ref<AgentSelectionOption[]>([])
const loadingAgents = ref(false), agentError = ref(false)
const previewing = ref(false)
const query = ref<string | null>('')
const validSelection = computed(() => single ? selected.value.length === 1 && !selected.value[0]!.is_collection : selected.value.length > 0)
const browser = useTemplateRef<InstanceType<typeof AgentFileBrowser>>('browser')
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
function confirm(): void { if (!busy && selectedAgent.value !== null && validSelection.value) emit('select', selected.value, selectedAgent.value) }
watch(selectedAgent, () => { selected.value = []; previewing.value = false; query.value = '' })
watch(open, value => { selected.value = []; if (value) void loadAgents(); else { request?.abort(); previewing.value = false } }, { immediate: true })
onBeforeUnmount(() => request?.abort())
</script>
<style scoped>
.internal-file-picker { width: 1000px; max-width: 96vw; height: 740px; max-height: 92dvh; }
.picker-toolbar { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); align-items: center; gap: 8px; padding: 8px; flex-shrink: 0; }
.picker-agent, .picker-search { min-width: 0; }
.picker-search { display: flex; align-items: center; gap: 4px; }
.picker-toolbar :deep(.q-field__control), .picker-toolbar :deep(.q-field__marginal) { height: 44px; min-height: 44px; }
.picker-footer { flex-shrink: 0; }
.picker-footer-content { display: flex; align-items: center; gap: 8px; padding: 6px 8px; }
.picker-selection { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; min-height: 28px; }
.picker-selection > .text-caption { flex-shrink: 0; }
.picker-selected-items { display: flex; flex: 1; min-width: 0; flex-wrap: wrap; max-height: 100px; overflow: auto; gap: 4px; }
.picker-selected-items :deep(.q-chip) { margin: 0; max-width: 100%; }
.picker-footer-content > .q-card__actions { flex-shrink: 0; }
@media (max-width: 1023px) { .picker-footer-content { flex-wrap: wrap; } .picker-selection { flex-basis: 100%; } .picker-footer-content > .q-card__actions { width: 100%; } }
@media (max-width: 1023px) { .internal-file-picker { width: 100%; max-width: 100%; height: 100%; max-height: 100%; } }
</style>
