<template>
  <q-select :model-value="modelValue" :options="options" option-value="id" option-label="label" emit-value map-options
    @update:model-value="emit('update:modelValue', $event)">
    <template #selected>
      <div class="row items-center no-wrap full-width">
        <AgentAvatar v-if="modelValue != null" :agent-id="modelValue" :name="selected?.label ?? displayValue" :has-avatar="selected?.has_avatar" size="28px" class="q-mr-sm" />
        <span class="col">{{ displayValue ?? selected?.label }}</span>
      </div>
    </template>
    <template #option="scope">
      <q-item v-bind="scope.itemProps" :aria-label="scope.opt.label">
        <q-item-section v-if="scope.opt.id != null" avatar>
          <AgentAvatar :agent-id="scope.opt.id" :name="scope.opt.label" :has-avatar="scope.opt.has_avatar" size="32px" />
        </q-item-section>
        <q-item-section>{{ scope.opt.label }}</q-item-section>
      </q-item>
    </template>
  </q-select>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { AgentAvatar } from '@/app/agent'
import type { ProcessAgentOption } from '../services/nativeProcessService'
const props = defineProps<{ modelValue: number | null; options: (ProcessAgentOption | { id: null; label: string; has_avatar?: boolean })[]; displayValue?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: number | null] }>()
const selected = computed(() => props.options.find(option => option.id === props.modelValue))
</script>
