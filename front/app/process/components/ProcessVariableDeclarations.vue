<template>
  <section class="q-gutter-y-xs" :aria-label="label">
    <div><strong>{{ label }}</strong></div>
    <div v-if="!modelValue.length" class="text-caption">{{ t('nativeProcesses.variables.empty') }}</div>
    <div v-else class="variable-table" tabindex="0">
      <table :aria-label="label">
        <thead><tr>
          <th v-if="!readonly" scope="col" class="drag-column" :aria-label="t('nativeProcesses.variables.order')"></th>
          <th scope="col" class="name-column">{{ t('nativeProcesses.variables.name') }}</th>
          <th scope="col" class="type-column">{{ t('nativeProcesses.variables.type') }}</th>
          <th scope="col" class="nullable-column">{{ t('nativeProcesses.variables.nullable') }}</th>
          <th scope="col">{{ t('nativeProcesses.variables.defaultJson') }}</th>
          <th v-if="!readonly" scope="col" class="actions-column" :aria-label="t('nativeProcesses.variables.actions')"></th>
        </tr></thead>
        <tbody><tr v-for="(variable, index) in modelValue" :key="index" :class="{
          'drop-before': drag?.moved && drag.to === index && index < drag.from,
          'drop-after': drag?.moved && drag.to === index && index > drag.from,
        }">
          <td v-if="!readonly" class="drag-column"><q-btn flat round dense icon="drag_indicator" class="drag-handle"
            :aria-label="t('nativeProcesses.variables.reorder', { name: variable.name })"
            @pointerdown.stop="startDrag($event, index)" @pointermove.stop="moveDrag" @pointerup.stop="finishDrag"
            @pointercancel="cancelDrag" @lostpointercapture="cancelDrag" @keydown.esc.prevent.stop="cancelDrag"
            @keydown.up.prevent.stop="move(index, index - 1, $event)" @keydown.down.prevent.stop="move(index, index + 1, $event)" /></td>
          <td><q-input :model-value="variable.name" dense outlined hide-bottom-space no-error-icon :readonly="readonly"
            :aria-label="t('nativeProcesses.variables.name')" :error="!validName(index)"
            @update:model-value="update(index, { name: String($event ?? '') })" /></td>
          <td><q-select :model-value="variable.type" :options="valueTypes" dense outlined hide-bottom-space :readonly="readonly"
            :aria-label="t('nativeProcesses.variables.type')" @update:model-value="changeType(index, $event)" /></td>
          <td class="nullable-column"><q-toggle :model-value="variable.nullable" :disable="readonly" dense
            :aria-label="t('nativeProcesses.variables.nullable')" @update:model-value="update(index, { nullable: Boolean($event) })" /></td>
          <td><q-input :model-value="drafts[index] ?? (variable.default === undefined ? '' : JSON.stringify(variable.default.value))"
            outlined dense hide-bottom-space autogrow type="textarea" :readonly="readonly"
            :aria-label="t('nativeProcesses.variables.defaultJson')" :placeholder="t('nativeProcesses.variables.noDefault')"
            :error="Boolean(invalid[index])" :error-message="t('nativeProcesses.variables.invalidDefault')" @update:model-value="setDefault(index, String($event ?? ''))" /></td>
          <td v-if="!readonly" class="actions-column"><q-btn flat round dense icon="delete_outline" :aria-label="t('nativeProcesses.variables.remove', { name: variable.name })" @click="remove(index)" /></td>
        </tr></tbody>
      </table>
    </div>
    <q-btn v-if="!readonly" outline dense no-caps size="sm" color="primary" icon="add" class="q-px-sm"
      :label="t('nativeProcesses.variables.add')" @click="add" />
  </section>
</template>
<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { valueTypes, type ValueType, type ProcessVariable, type JsonValue } from '../services/nativeProcessService'
const props = defineProps<{ modelValue: ProcessVariable[]; label: string; readonly?: boolean; draftValues?: Record<number, string> }>()
const emit = defineEmits<{ 'update:modelValue': [value: ProcessVariable[]]; 'update:draftValues': [value: Record<number, string>]; validity: [valid: boolean] }>()
const { t } = useI18n()
const drafts = ref<Record<number, string>>({ ...props.draftValues }), invalid = ref<Record<number, boolean>>({})
const drag = ref<{ pointerId: number; from: number; to: number | null; startY: number; moved: boolean; handle: HTMLElement; table: HTMLTableElement } | null>(null)
for (const [index, value] of Object.entries(drafts.value)) { if (value.trim()) { try { JSON.parse(value) } catch { invalid.value[Number(index)] = true } } }
watch(drafts, value => emit('update:draftValues', { ...value }), { deep: true })
function initial(type: ValueType): JsonValue { return type === 'array' ? [] : type === 'object' ? {} : type === 'bool' ? false : ['int', 'float', 'Agent', 'User'].includes(type) ? 1 : '' }
function update(index: number, value: Partial<ProcessVariable>): void {
  emit('update:modelValue', props.modelValue.map((variable, at) => at === index ? { ...variable, ...value } : variable))
}
function validName(index: number): boolean { const name = props.modelValue[index]?.name ?? ''; return Boolean(name.trim()) && name === name.trim() && props.modelValue.filter(variable => variable.name === name).length === 1 }
function add(): void { emit('update:modelValue', [...props.modelValue, { name: '', type: 'string', nullable: true }]) }
function applyOrder(order: number[]): void {
  const nextDrafts: Record<number, string> = {}, nextInvalid: Record<number, boolean> = {}
  order.forEach((previous, index) => {
    if (previous in drafts.value) nextDrafts[index] = drafts.value[previous]!
    if (previous in invalid.value) nextInvalid[index] = invalid.value[previous]!
  })
  drafts.value = nextDrafts; invalid.value = nextInvalid
  emit('update:modelValue', order.map(index => props.modelValue[index]!))
}
function remove(index: number): void { applyOrder(props.modelValue.map((_, at) => at).filter(at => at !== index)) }
function move(from: number, to: number, event?: Event): void {
  if (props.readonly || from === to || to < 0 || to >= props.modelValue.length) return
  const table = (event?.currentTarget as HTMLElement | null)?.closest('table')
  const order = props.modelValue.map((_, index) => index)
  order.splice(to, 0, order.splice(from, 1)[0]!)
  applyOrder(order)
  if (table) void nextTick(() => table.querySelectorAll<HTMLButtonElement>('.drag-handle')[to]?.focus())
}
function startDrag(event: PointerEvent, index: number): void {
  if (props.readonly || event.button !== 0) return
  const handle = event.currentTarget as HTMLElement, table = handle.closest('table')
  if (!table) return
  drag.value = { pointerId: event.pointerId, from: index, to: index, startY: event.clientY, moved: false, handle, table }
  handle.setPointerCapture(event.pointerId)
}
function moveDrag(event: PointerEvent): void {
  const current = drag.value
  if (!current || current.pointerId !== event.pointerId) return
  if (Math.abs(event.clientY - current.startY) < 4 && !current.moved) return
  event.preventDefault(); current.moved = true
  const bounds = current.table.getBoundingClientRect()
  current.to = null
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) return
  let distance = Infinity
  Array.from(current.table.tBodies[0]!.rows).forEach((row, index) => {
    const rect = row.getBoundingClientRect(), delta = Math.abs(event.clientY - (rect.top + rect.height / 2))
    if (delta < distance) { distance = delta; current.to = index }
  })
}
function finishDrag(event: PointerEvent): void {
  const current = drag.value
  if (!current || current.pointerId !== event.pointerId) return
  moveDrag(event)
  cancelDrag()
  if (current.moved && current.to !== null) move(current.from, current.to, event)
}
function cancelDrag(): void {
  const current = drag.value
  drag.value = null
  if (current?.handle.hasPointerCapture(current.pointerId)) current.handle.releasePointerCapture(current.pointerId)
}
watch(() => [props.readonly, props.modelValue], cancelDrag)
function changeType(index: number, value: ValueType): void { delete drafts.value[index]; delete invalid.value[index]; update(index, { type: value, ...(props.modelValue[index]?.default !== undefined ? { default: { type: value, value: initial(value) } } : {}) }) }
function setDefault(index: number, text: string): void {
  drafts.value[index] = text
  if (!text.trim()) {
    delete invalid.value[index]
    emit('update:modelValue', props.modelValue.map((entry, at) => { const copy = { ...entry }; if (at === index) delete copy.default; return copy }))
    return
  }
  try { const value = JSON.parse(text) as JsonValue; update(index, { default: { type: props.modelValue[index]!.type, value } }); invalid.value[index] = false }
  catch { invalid.value[index] = true }
}
watch(() => [props.modelValue, invalid.value], () => emit('validity', !Object.values(invalid.value).some(Boolean) && props.modelValue.every((_, index) => validName(index))), { immediate: true, deep: true })
</script>
<style scoped>
.variable-table { overflow-x: auto; border: 1px solid var(--q-separator-color, rgba(128, 128, 128, .24)); border-radius: 8px; }
table { width: 100%; min-width: 520px; border-collapse: collapse; table-layout: fixed; }
th { text-align: left; font-size: 12px; font-weight: 500; }
th, td { padding: 3px 4px; vertical-align: middle; }
tbody tr { border-top: 1px solid var(--q-separator-color, rgba(128, 128, 128, .24)); }
.name-column { width: 25%; }
.type-column { width: 20%; }
.drag-column { width: 30px; padding-left: 0; padding-right: 0; text-align: center; }
.drag-handle { cursor: grab; touch-action: none; }
.drag-handle:active { cursor: grabbing; }
.drop-before { box-shadow: inset 0 2px var(--solaire-blue-accent); }
.drop-after { box-shadow: inset 0 -2px var(--solaire-blue-accent); }
.nullable-column { width: 76px; text-align: center; }
.actions-column { width: 42px; text-align: center; }
.variable-table :deep(.q-field--dense .q-field__control) { height: 30px; min-height: 30px; padding: 0 6px; }
.variable-table :deep(.q-field--dense .q-field__marginal) { height: 30px; }
.variable-table :deep(.q-field--dense .q-field__native) { min-height: 30px; padding: 2px 0; }
.variable-table :deep(.q-textarea.q-field--dense .q-field__control) { height: auto; }
.variable-table :deep(.q-textarea .q-field__control-container) { padding: 0; }
.variable-table :deep(.q-textarea.q-field--dense .q-field__native) { padding: 6px 0; }
</style>
