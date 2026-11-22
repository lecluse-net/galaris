<template>
  <q-dialog v-model="open">
    <q-card class="galaris-dialog-card conversation-tools-dialog">
      <DialogHeader :title="t('services.conversationTools.title', { name: label })" :close-label="t('common.close')" />
      <q-card-section class="galaris-dialog-body">
        <p>{{ t(tool?.can_edit ? 'services.conversationTools.scope' : 'services.conversationTools.builtIn') }}</p>
        <q-banner v-if="loadError" dense role="alert" class="q-mb-md">
          {{ t('services.conversationTools.loadError') }}
          <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="load(failedAfterId)" /></template>
        </q-banner>
        <q-banner v-if="saveError" dense role="alert" class="q-mb-md">
          {{ t('services.conversationTools.saveError') }}
        </q-banner>
        <q-banner v-if="discoveryIncomplete" dense role="status" class="q-mb-md">
          {{ t('services.conversationTools.discoveryIncomplete') }}
        </q-banner>
        <q-table v-if="rows.length || !loadError" flat bordered wrap-cells
          :rows="rows" :columns="columns" row-key="key" :loading="loading"
          :pagination="{ rowsPerPage: 50 }" :rows-per-page-options="[10, 20, 50, 100, 500]"
          :no-data-label="t('services.conversationTools.empty')">
          <template #body-cell-enabled="slot">
            <q-td :props="slot">
              <q-toggle v-if="editable" :model-value="slot.row.enabled" color="primary"
                :disable="loading || saving || loadError"
                :aria-label="t('services.conversationTools.toggle', {
                  name: slot.row.name, source: t(`services.conversationTools.${slot.row.source}`),
                })" @update:model-value="enabled => save(slot.row, enabled)" />
              <span v-else>{{ t(slot.row.enabled ? 'services.conversationTools.allowed' : 'services.conversationTools.disallowed') }}</span>
            </q-td>
          </template>
        </q-table>
        <q-btn v-if="nextConnectionId != null" class="q-mt-md" outline color="primary"
          :label="t('services.conversationTools.loadMore')" :loading="loading" :disable="saving || loadError"
          @click="load(nextConnectionId)" />
        <q-form v-if="editable && tool?.has_mcp" class="row items-start q-col-gutter-sm q-mt-md"
          @submit="addExternal">
          <div class="col">
            <q-input v-model.trim="externalName" outlined dense hide-bottom-space
              :label="t('services.conversationTools.exactName')" :disable="loading || saving || loadError"
              :rules="[validName]" />
          </div>
          <div class="col-auto">
            <q-btn type="submit" outline color="primary" :label="t('services.conversationTools.allowTool')"
              :disable="!externalName || loading || saving || loadError" />
          </div>
        </q-form>
      </q-card-section>
      <q-card-actions align="right" class="galaris-dialog-actions">
        <q-btn v-if="editable && tool?.has_mcp" outline color="primary" :label="t('common.refresh')"
          :loading="loading" :disable="saving" @click="load()" />
        <q-btn outline color="primary" :label="t('common.close')" v-close-popup />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { QTableColumn } from 'quasar'
import { useI18n } from 'vue-i18n'
import { DialogHeader } from '@/core/util'
import serviceApi, { type ConversationToolEntry, type Service } from '../services/serviceApi'

const open = defineModel<boolean>({ required: true })
const { tool, label, canEdit } = defineProps<{ tool: Service | null; label: string; canEdit: boolean }>()
const { t } = useI18n()
const editable = computed(() => canEdit && !!tool?.can_edit)
const tools = ref<ConversationToolEntry[]>([])
const rows = computed(() => tools.value.map(entry => ({ ...entry, key: `${entry.source}:${entry.name}` })))
const columns = computed<QTableColumn[]>(() => [
  { name: 'enabled', field: 'enabled', label: t('services.conversationTools.allowed'), align: 'left' },
  { name: 'name', field: 'name', label: t('services.conversationTools.tool'), align: 'left', style: 'overflow-wrap: anywhere' },
  { name: 'source', field: entry => t(`services.conversationTools.${entry.source}`),
    label: t('services.conversationTools.source'), align: 'left' },
])
const externalName = ref('')
const loading = ref(false)
const saving = ref(false)
const loadError = ref(false)
const saveError = ref(false)
const discoveryIncomplete = ref(false)
const nextConnectionId = ref<number | null>(null)
let failedAfterId: number | undefined
let request: AbortController | undefined
let pendingSave: ReturnType<typeof serviceApi.setConversationTool> | undefined

function validName(name: string): boolean | string {
  return (new TextEncoder().encode(name).length <= 255 && !name.includes('\x00'))
    || t('services.conversationTools.invalidName')
}

async function load(afterConnectionId?: number): Promise<void> {
  if (!open.value || !tool) return
  const serviceId = tool.id
  const discover = editable.value && tool.has_mcp
  request?.abort()
  const current = request = new AbortController()
  loading.value = true
  loadError.value = false
  saveError.value = false
  try {
    await pendingSave?.catch(() => undefined)
    if (current.signal.aborted) return
    const { data } = await serviceApi.getConversationTools(serviceId, discover, current.signal, afterConnectionId)
    if (current.signal.aborted) return
    if (afterConnectionId == null) {
      tools.value = data.tools
      discoveryIncomplete.value = data.discovery_incomplete
    } else {
      const entries = new Map(rows.value.map(({ name, source, key }) => [key, { name, source, enabled: false }]))
      for (const entry of data.tools) entries.set(`${entry.source}:${entry.name}`, entry)
      tools.value = [...entries.values()]
      discoveryIncomplete.value ||= data.discovery_incomplete
    }
    nextConnectionId.value = data.next_connection_id
  } catch {
    if (!current.signal.aborted) {
      failedAfterId = afterConnectionId
      loadError.value = true
    }
  } finally {
    if (!current.signal.aborted) loading.value = false
  }
}

async function save(entry: ConversationToolEntry, enabled: boolean): Promise<void> {
  if (!tool || !open.value || !editable.value || loading.value || loadError.value || saving.value) return
  const current = request
  const updated = { name: entry.name, source: entry.source, enabled }
  saving.value = true
  saveError.value = false
  try {
    const { data } = await (pendingSave = serviceApi.setConversationTool(tool.id, updated))
    if (current?.signal.aborted) return
    const index = tools.value.findIndex(row => row.name === entry.name && row.source === entry.source)
    updated.enabled = data.enabled
    if (index === -1) tools.value.push(updated)
    else tools.value[index] = updated
    if (entry.source === 'external' && externalName.value === entry.name) externalName.value = ''
  } catch {
    if (!current?.signal.aborted) saveError.value = true
  } finally {
    pendingSave = undefined
    saving.value = false
  }
}

function addExternal(): void {
  const name = externalName.value
  if (name && validName(name) === true) void save({ name, source: 'external', enabled: false }, true)
}

watch(() => [open.value, tool?.id, editable.value] as const, ([visible]) => {
  request?.abort()
  tools.value = []
  externalName.value = ''
  discoveryIncomplete.value = false
  nextConnectionId.value = null
  if (visible) void load()
}, { immediate: true })
onBeforeUnmount(() => request?.abort())
</script>

<style scoped>
.conversation-tools-dialog { width: min(760px, 95vw); max-width: 95vw; }
</style>
