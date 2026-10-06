<template>
  <section v-if="allowed" class="q-pa-sm" :aria-label="t('memory.dream.title')">
    <q-spinner v-if="loading" color="primary" />
    <template v-else-if="actions.length">
      <div v-if="disabled" class="text-caption q-mb-sm">{{ t('memory.dream.saveFirst') }}</div>
      <div class="row q-gutter-sm">
        <q-btn v-for="action in actions" :key="action" outline no-caps color="primary"
          :icon="icons[action]" :label="t(`memory.dream.actions.${action}`)"
          :title="action === 'structure' ? t(props.nodeKind === 'folder' ? 'memory.dream.structureFolderHint' : 'memory.dream.structureDocumentHint') : undefined"
          :loading="running === action" :disable="disabled || running !== null" @click="run(action)" />
      </div>
    </template>
    <q-btn v-if="loadFailed" flat no-caps color="primary" :label="t('memory.dream.retry')" @click="load" />
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { memoryService, type MemoryDreamAction } from '../services/memoryService'
import type { MemoryNodeKind } from '../types'

const props = defineProps<{ itemId: string; agentId: number | null; nodeKind?: MemoryNodeKind | 'conversation'; disabled?: boolean }>()
const emit = defineEmits<{ completed: [id: string, action: MemoryDreamAction]; busy: [value: boolean] }>()
const { t } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const allowed = computed(() => props.agentId !== null && (privilegeStore.hasPrivilege(privileges.MEMORY_EDIT)
  || privilegeStore.hasPrivilege(privileges.MEMORY_ADMIN)))
const actions = ref<MemoryDreamAction[]>([])
const loading = ref(false)
const running = ref<MemoryDreamAction | null>(null)
const loadFailed = ref(false)
const icons: Record<MemoryDreamAction, string> = {
  describe: 'description', read_document: 'document_scanner', thumbnail: 'image', findings: 'fact_check', structure: 'account_tree',
}
let generation = 0

async function load(): Promise<void> {
  const request = ++generation
  actions.value = []
  loadFailed.value = false
  running.value = null
  emit('busy', false)
  loading.value = allowed.value
  const agentId = props.agentId
  if (!allowed.value || agentId === null) return
  try {
    const result = await memoryService.dreamActions(props.itemId, agentId)
    if (request === generation) actions.value = result
  } catch (exc) {
    if (request === generation && ![403, 404].includes((exc as { response?: { status?: number } }).response?.status ?? 0)) {
      loadFailed.value = true
      $q.notify({ type: 'negative', message: t('memory.dream.loadError') })
    }
  } finally {
    if (request === generation) loading.value = false
  }
}

async function run(action: MemoryDreamAction): Promise<void> {
  if (running.value || props.disabled || props.agentId === null) return
  const request = generation
  const id = props.itemId
  const agentId = props.agentId
  running.value = action
  emit('busy', true)
  try {
    const result = await memoryService.runDreamAction(id, agentId, action, props.nodeKind)
    if (request !== generation) return
    $q.notify({
      type: result.result_count ? 'positive' : 'info',
      message: t(result.result_count ? 'memory.dream.done' : 'memory.dream.noChange'),
    })
    emit('completed', id, action)
  } catch {
    if (request === generation) $q.notify({ type: 'negative', message: t('memory.dream.runError') })
  } finally {
    if (request === generation) {
      running.value = null
      emit('busy', false)
    }
  }
}

watch(() => [props.itemId, props.agentId, allowed.value], load, { immediate: true })
onBeforeUnmount(() => { generation++; emit('busy', false) })
</script>
