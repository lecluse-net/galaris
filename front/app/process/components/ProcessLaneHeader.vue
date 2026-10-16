<template>
  <div class="lane-header" :style="{ width: `${laneHeaderWidth}px` }" :class="{ 'human-header': actor?.kind === 'human', 'flow-header': !actor }" @pointerdown.stop>
    <div v-if="actor" class="lane-title">
      <q-btn v-if="actor && !readonly" flat round dense icon="drag_indicator" class="lane-drag-handle" :aria-label="t('nativeProcesses.reorderActor', { name: actor.name })"
        @pointerdown.stop.prevent="emit('reorderStart', $event)" @lostpointercapture="emit('reorderCancel')"
        @keydown.up.prevent="emit('reorder', -1)" @keydown.down.prevent="emit('reorder', 1)">
        <q-tooltip>{{ t('nativeProcesses.reorderActor', { name: actor.name }) }}</q-tooltip>
      </q-btn>
      <q-input v-if="actor && !readonly" :model-value="actor.name" outlined dense hide-bottom-space class="lane-name"
        :aria-label="t('nativeProcesses.actorName')" :placeholder="t('nativeProcesses.newActor')" @update:model-value="emit('update', { name: String($event ?? '') })" />
      <strong v-else-if="actor">{{ actor.name }}</strong>
      <q-btn v-if="actor && !readonly" flat round dense color="negative" icon="delete_outline" :disable="used"
        :aria-label="t('nativeProcesses.removeActor', { name: actor.name })" @click="emit('remove')">
        <q-tooltip>{{ t('nativeProcesses.removeActor', { name: actor.name }) }}</q-tooltip>
      </q-btn>
    </div>
    <ProcessAgentSelect v-if="actor?.kind === 'agent' && !readonly" :model-value="actor.agent_id" :options="agents" borderless dense clearable hide-bottom-space
      :display-value="assignment" :aria-label="t('nativeProcesses.assignedAgent')" @update:model-value="emit('update', { agent_id: $event })" />
    <q-select v-else-if="actor?.kind === 'human' && !readonly" :model-value="actor.user_id" :options="humans"
      option-value="id" option-label="label" emit-value map-options borderless dense clearable hide-bottom-space
      :loading="humansLoading" :display-value="assignment" :aria-label="t('nativeProcesses.assignedHuman')"
      @popup-show="emit('reloadHumans')" @update:model-value="emit('update', { user_id: $event })">
      <template #no-option>
        <q-item><q-item-section>{{ t(humansLoading ? 'nativeProcesses.loadingHumans' : humansError ? 'nativeProcesses.humanOptionsError' : 'nativeProcesses.noHumans') }}</q-item-section></q-item>
        <q-item v-if="humansError" clickable @click="emit('reloadHumans')"><q-item-section>{{ t('nativeProcesses.retry') }}</q-item-section></q-item>
      </template>
    </q-select>
    <ProcessAgentSelect v-else-if="!actor && executionAgentId !== undefined" :model-value="executionAgentId" :options="[{ id: null, label: t('nativeProcesses.launchingAgent') }, ...agents]"
      borderless dense hide-bottom-space :readonly="!executionEditable" :label="t('nativeProcesses.agent')"
      :display-value="agents.find(agent => agent.id === executionAgentId)?.label ?? t('nativeProcesses.launchingAgent')" @update:model-value="emit('execution', $event)" />
    <div v-else-if="actor" class="lane-assignment row items-center no-wrap">
      <AgentAvatar v-if="actor.kind === 'agent' && actor.agent_id != null" :agent-id="actor.agent_id" :name="assignment" :has-avatar="agents.find(agent => agent.id === actor?.agent_id)?.has_avatar" size="28px" class="q-mr-sm" />
      <span class="col">{{ assignment }}</span>
    </div>
  </div>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { AgentAvatar } from '@/app/agent'
import type { ProcessActor, ProcessAgentOption } from '../services/nativeProcessService'
import { laneHeaderWidth } from '../graphEditing'
import ProcessAgentSelect from './ProcessAgentSelect.vue'
defineProps<{ actor: ProcessActor | null; readonly: boolean; used: boolean; assignment: string;
  agents: ProcessAgentOption[]; humans: { id: number; label: string }[];
  humansLoading?: boolean; humansError?: boolean;
  executionAgentId?: number | null; executionEditable: boolean }>()
const emit = defineEmits<{ update: [patch: Partial<ProcessActor>]; remove: []; execution: [id: number | null];
  reloadHumans: [];
  reorderStart: [event: PointerEvent]; reorderCancel: []; reorder: [direction: -1 | 1] }>()
const { t } = useI18n()
</script>
<style scoped>
.lane-header { height: 100%; background: var(--diagram-actor); color: var(--diagram-actor-text); border-right: 1px solid var(--diagram-separator); padding: 16px 12px; pointer-events: auto; }
.lane-header :deep(.q-field__native), .lane-header :deep(.q-field__input) { color: var(--diagram-actor-text); }
.lane-header :deep(.q-field__label), .lane-header :deep(.q-field__marginal), .lane-assignment { color: var(--diagram-actor-muted); }
.lane-header :deep(.q-field--outlined .q-field__control::before) { border-color: var(--diagram-actor-muted); }
.lane-title { display: flex; align-items: center; gap: 6px; min-height: 36px; }
.lane-title strong, .lane-name { flex: 1; min-width: 0; font-size: 16px; overflow-wrap: anywhere; }
.lane-name :deep(input) { font-weight: 700; font-size: 16px; }
.lane-title .q-btn { flex: 0 0 auto; }
.lane-drag-handle { touch-action: none; cursor: grab; }
.lane-header > .q-select { margin-top: 6px; font-size: 12px; }
.lane-assignment { margin-top: 10px; font-size: 12px; overflow-wrap: anywhere; }
</style>
