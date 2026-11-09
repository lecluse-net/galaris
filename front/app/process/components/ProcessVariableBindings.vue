<template>
  <div class="row q-col-gutter-sm">
    <div v-for="direction in directions" :key="direction" class="col-12 col-md-6">
      <q-select :model-value="direction === 'inputs' ? inputs : outputs" :options="options(direction)"
        multiple use-chips use-input input-debounce="0" emit-value map-options outlined dense hide-bottom-space
        :readonly="readonly" :label="t(`nativeProcesses.variables.${direction}`)"
        @filter="(value, update) => update(() => { searches[direction] = value })"
        @update:model-value="update(direction, $event)" />
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import type { NodeKind, ProcessVariable } from '../services/nativeProcessService'
import { allowsVariableDirection, type VariableDirection } from '../variableBindings'
const { inputs = [], outputs = [], variables, kind, readonly = false } = defineProps<{
  inputs?: string[]; outputs?: string[]; variables: ProcessVariable[]; kind?: NodeKind; readonly?: boolean
}>()
const emit = defineEmits<{ 'update:inputs': [value: string[]]; 'update:outputs': [value: string[]] }>()
const { t } = useI18n()
const directions = computed(() => (['inputs', 'outputs'] as VariableDirection[]).filter(direction => !kind || allowsVariableDirection(kind, direction)))
const searches = reactive({ inputs: '', outputs: '' })
function update(direction: VariableDirection, values: string[]): void {
  if (kind && !allowsVariableDirection(kind, direction)) return
  if (direction === 'inputs') emit('update:inputs', values)
  else emit('update:outputs', values)
}
function options(direction: VariableDirection): { value: string; label: string }[] {
  return variables.map(variable => ({ value: variable.name, label: variable.label ? `${variable.label} · ${variable.name}` : variable.name }))
    .filter(option => option.label.toLocaleLowerCase().includes(searches[direction].toLocaleLowerCase()))
}
</script>
