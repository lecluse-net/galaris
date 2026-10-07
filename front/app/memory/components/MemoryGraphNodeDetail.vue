<template>
  <q-card-section class="q-pa-none">
    <div v-if="showHeader" class="row items-start no-wrap q-gutter-sm">
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

    <MemoryNodeMetadata :node="node" :role-label="roleLabel" class="q-my-md" />
    <MemoryDreamActions :item-id="node.id" :agent-id="agentId" :node-kind="node.node_kind" />

    <MemoryFileResources v-if="node.node_kind === 'file'" :key="`${agentId}:${node.id}`" :item-id="node.id" :agent-id="agentId" />
    <DocumentThumbnail v-else-if="node.node_kind === 'document'" :document-id="node.id" :agent-id="agentId" />
    <div class="row q-gutter-sm q-mt-md">
      <MemoryAttachmentButton v-if="node.node_kind === 'attachment'" :item-id="node.id" :agent-id="agentId" show-thumbnail />
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
      <MemoryGraphRelations :relations="relations" @select="emit('select', $event)" />
    </template>
  </q-card-section>
</template>

<script setup lang="ts">
import DocumentIcon from './DocumentIcon.vue'
import MemoryDreamActions from './MemoryDreamActions.vue'
import MemoryAttachmentButton from './MemoryAttachmentButton.vue'
import MemoryFileResources from './MemoryFileResources.vue'
import DocumentThumbnail from './DocumentThumbnail.vue'
import MemoryNodeMetadata from './MemoryNodeMetadata.vue'
import MemoryGraphRelations from './MemoryGraphRelations.vue'
import { useI18n } from 'vue-i18n'
import type { MemoryGraphRelation, MemoryGraphNode } from '../types'

const { showHeader = true } = defineProps<{
  showHeader?: boolean
  agentId: number | null
  node: MemoryGraphNode
  relations: MemoryGraphRelation[]
  color: string
  icon: string
  roleLabel: string
}>()

const emit = defineEmits<{
  close: []
  open: [id: string]
  select: [id: string]
}>()

const { t } = useI18n()
</script>
