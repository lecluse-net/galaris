<template>
  <div class="q-gutter-y-xs variable-usage">
    <div v-for="direction in directions" :key="direction">
      <div class="text-caption">{{ t(`nativeProcesses.variables.usedAs.${direction}`) }}</div>
      <q-select :model-value="variableUsage(graph, name, direction)" :options="options(direction)" multiple use-chips
        use-input input-debounce="0" emit-value map-options outlined dense hide-bottom-space :readonly="readonly"
        :aria-label="t(`nativeProcesses.variables.usageLabel.${direction}`, { name })"
        @filter="(value, update) => update(() => { searches[direction] = value })"
        @update:model-value="emit('update:graph', setVariableUsage(graph, name, direction, $event))" />
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import type { BpmnGraph } from '../services/nativeProcessService'
import { allowsVariableDirection, variableConsumers, variableUsage, setVariableUsage, type VariableDirection } from '../variableBindings'
const { graph, name, readonly = false } = defineProps<{ graph: BpmnGraph; name: string; readonly?: boolean }>()
const emit = defineEmits<{ 'update:graph': [value: BpmnGraph] }>()
const { t } = useI18n()
const directions: VariableDirection[] = ['inputs', 'outputs']
const searches = reactive({ inputs: '', outputs: '' })
const consumers = computed(() => variableConsumers(graph).map(consumer => ({ value: consumer.key, kind: consumer.node.kind,
  label: `${consumer.node.title || t(`nativeProcesses.kinds.${consumer.node.kind}`)} · ${consumer.path.join(' / ')}` })))
function options(direction: VariableDirection): { value: string; label: string }[] {
  return consumers.value.filter(option => allowsVariableDirection(option.kind, direction)
    && option.label.toLocaleLowerCase().includes(searches[direction].toLocaleLowerCase()))
}
</script>
<style scoped>
.variable-usage :deep(.q-chip) { max-width: calc(100% - 8px); }
.variable-usage :deep(.q-chip__content) { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
</style>
