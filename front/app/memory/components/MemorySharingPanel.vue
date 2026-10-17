<template>
  <ResourceSharingPanel :item-id="itemId" :editable="editable" :lock-version="lockVersion"
    :reader="reader ?? defaultReader" :writer="writer ?? defaultWriter"
    @changed="$emit('changed')" @permission="$emit('permission', $event)">
    <template #avatar="{ recipient, size }">
      <AgentAvatar v-if="recipient.kind === 'agent'" :agent-id="recipient.id" :name="recipient.label" :has-avatar="recipient.has_avatar" :size="size" />
      <PersonAvatar v-else :name="recipient.label" :avatar-url="recipient.avatar_url" :size="size" />
    </template>
  </ResourceSharingPanel>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { AgentAvatar } from '@/app/agent'
import { PersonAvatar } from '@/core/util'
import { ResourceSharingPanel, type SharingState, type SharingUpdate } from '@/app/share'
import { memoryService } from '../services/memoryService'
const props = withDefaults(defineProps<{ itemId: string; editable: boolean; lockVersion?: number;
  resourceKind?: 'memory' | 'document'; reader?: (id: string) => Promise<SharingState>;
  writer?: (id: string, data: SharingUpdate) => Promise<SharingState>
}>(), { resourceKind: 'memory' })
defineEmits<{ changed: []; permission: [value: boolean] }>()
const defaultReader = computed(() => props.resourceKind === 'document' ? memoryService.documentSharing : memoryService.itemSharing)
const defaultWriter = computed(() => props.resourceKind === 'document' ? memoryService.updateDocumentSharingLevel : memoryService.updateItemSharing)
</script>
