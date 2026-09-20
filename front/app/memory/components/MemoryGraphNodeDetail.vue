<template>
  <q-card-section class="q-pa-none">
    <div class="row items-start no-wrap q-gutter-sm">
      <DocumentIcon v-if="node.node_kind === 'document'" :document-id="node.id" :title="node.title" size="28px" />
      <q-avatar v-else
        :style="{ backgroundColor: color }"
        text-color="white"
        :icon="icon"
        size="40px"
      />
      <div class="col">
        <div class="text-subtitle1 text-weight-medium">{{ node.title }}</div>
        <div class="text-caption text-grey-7">
          {{ roleLabel }}
          · {{ t(`memory.visibilities.${node.visibility}`) }}
        </div>
      </div>
      <q-btn
        flat
        round
        dense
        icon="close"
        :aria-label="t('memory.graph.closeDetails')"
        @click="emit('close')"
      >
        <q-tooltip>{{ t('memory.graph.closeDetails') }}</q-tooltip>
      </q-btn>
    </div>

    <q-list dense class="q-mt-md">
      <q-item>
        <q-item-section avatar><q-icon name="update" color="primary" /></q-item-section>
        <q-item-section>
          <q-item-label caption>{{ t('memory.graph.lastActivity') }}</q-item-label>
          <q-item-label>{{ formatDate(node.activity_at) }}</q-item-label>
        </q-item-section>
      </q-item>
      <q-item>
        <q-item-section avatar><q-icon name="visibility" color="primary" /></q-item-section>
        <q-item-section>
          <q-item-label caption>{{ t('memory.accessCount') }}</q-item-label>
          <q-item-label>{{ formatNumber(node.access_count) }}</q-item-label>
        </q-item-section>
      </q-item>
    </q-list>

    <div class="row q-gutter-sm q-mt-md">
      <MemoryAttachmentButton v-if="node.node_kind === 'attachment'" :item-id="node.id" :agent-id="agentId" />
      <q-btn
        v-if="node.node_kind !== 'conversation' && node.node_kind !== 'folder'"
        color="primary"
        icon="visibility"
        :label="t('memory.view')"
        @click="emit('open', node.id)"
      />
    </div>

    <template v-if="relations.length">
      <q-separator class="q-my-md" />
      <div class="text-caption text-grey-7 q-mb-xs">{{ t('memory.links') }}</div>
      <q-list dense separator bordered class="memory-graph__relations">
        <q-item
          v-for="relation in relations"
          :key="relation.edge.id"
          clickable
          @click="emit('select', relation.other.id)"
        >
          <q-item-section avatar>
            <DocumentIcon v-if="relation.other.node_kind === 'document'" :document-id="relation.other.id" :title="relation.other.title" />
            <q-icon v-else name="account_tree" color="primary" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ relation.other.title }}</q-item-label>
            <q-item-label caption>{{ relation.edge.relation_type }}</q-item-label>
          </q-item-section>
          <q-item-section side><q-icon name="chevron_right" /></q-item-section>
        </q-item>
      </q-list>
    </template>
  </q-card-section>
</template>

<script setup lang="ts">
import DocumentIcon from './DocumentIcon.vue'
import MemoryAttachmentButton from './MemoryAttachmentButton.vue'
import { useI18n } from 'vue-i18n'
import type { MemoryGraphEdge, MemoryGraphNode } from '../types'

defineProps<{
  agentId: number | null
  node: MemoryGraphNode
  relations: Array<{
    edge: MemoryGraphEdge
    other: MemoryGraphNode
  }>
  color: string
  icon: string
  roleLabel: string
}>()

const emit = defineEmits<{
  close: []
  open: [id: string]
  select: [id: string]
}>()

const { t, locale } = useI18n()

function formatDate(value: string | number | Date | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat(locale.value).format(value)
}
</script>

<style scoped>
:global(body.body--dark) .memory-graph__relations {
  border-color: rgba(255, 255, 255, 0.14);
  background: #20242c;
}

:global(body.body--dark) .memory-graph__relations :deep(.q-item + .q-item) {
  border-color: rgba(255, 255, 255, 0.1);
}

:global(body.body--dark) .memory-graph__relations :deep(.q-item:hover) {
  background: rgba(144, 202, 249, 0.08);
}
</style>
