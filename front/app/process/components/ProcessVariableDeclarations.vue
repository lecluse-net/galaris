<template>
  <section class="q-gutter-y-xs" :aria-label="label">
    <div><strong>{{ label }}</strong></div>
    <div v-if="!modelValue.length" class="text-caption">{{ t('nativeProcesses.variables.empty') }}</div>
    <div v-else class="variable-table" tabindex="0">
      <table :aria-label="label" :class="{ 'with-usage': Boolean($slots.usage) }">
        <thead><tr>
          <th v-if="!readonly" scope="col" class="drag-column" :aria-label="t('nativeProcesses.variables.order')"></th>
          <th scope="col" class="name-column">{{ t('nativeProcesses.variables.name') }}</th>
          <th scope="col" class="type-column">{{ t('nativeProcesses.variables.type') }}</th>
          <th scope="col" class="nullable-column">{{ t('nativeProcesses.variables.nullable') }}</th>
          <th scope="col">{{ t('nativeProcesses.variables.defaultJson') }}</th>
          <th v-if="$slots.usage" scope="col" class="usage-column">{{ t('nativeProcesses.variables.uses') }}</th>
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
          <td><q-input :model-value="nameDrafts[index] ?? variable.name" dense outlined hide-bottom-space no-error-icon :readonly="readonly"
            :aria-label="t('nativeProcesses.variables.name')" :error="!validName(index)"
            @update:model-value="setName(index, String($event ?? ''))" />
            <q-input :model-value="variable.label ?? ''" dense outlined hide-bottom-space class="q-mt-xs" :readonly="readonly"
              :label="t('nativeProcesses.variables.label')" maxlength="200" @update:model-value="update(index, { label: String($event ?? '') })" />
            <q-input :model-value="variable.description ?? ''" dense outlined hide-bottom-space autogrow type="textarea" class="q-mt-xs" :readonly="readonly"
              :label="t('nativeProcesses.variables.description')" maxlength="4000" @update:model-value="update(index, { description: String($event ?? '') })" />
          </td>
          <td>
            <q-select :model-value="variable.type" :options="typeOptions" emit-value map-options use-input input-debounce="0"
              :display-value="t(`nativeProcesses.variables.types.${variable.type}`)"
              dense outlined hide-bottom-space :readonly="readonly" @filter="filterTypes"
              :aria-label="t('nativeProcesses.variables.type')" @update:model-value="changeType(index, $event)" />
            <div v-if="variable.type === 'date' || variable.type === 'datetime'" class="text-caption q-mt-xs">
              {{ t(`nativeProcesses.variables.${variable.type}Hint`) }}
            </div>
            <template v-if="variable.type === 'Document'">
              <div class="text-caption q-mt-xs">{{ t('nativeProcesses.variables.documentType') }}</div>
              <q-select :model-value="variable.document_type ?? null" :options="documentOptions"
                emit-value map-options clearable dense outlined hide-bottom-space :readonly="readonly"
                :aria-label="t('nativeProcesses.variables.documentType')"
                :display-value="variable.document_type ? t(`documents.types.${variable.document_type}`) : t('nativeProcesses.variables.anyDocument')"
                @update:model-value="setConstraint(index, 'document_type', $event)" />
            </template>
            <template v-if="variable.type === 'File'">
              <div class="text-caption q-mt-xs">{{ t('nativeProcesses.variables.mimeType') }}</div>
              <q-select :model-value="variable.mime_type ?? null" :options="mimeOptions"
                emit-value map-options clearable use-input new-value-mode="add-unique" input-debounce="0" @filter="filterMimes"
                dense outlined hide-bottom-space :readonly="readonly"
                :aria-label="t('nativeProcesses.variables.mimeType')" :display-value="mimeLabel(variable.mime_type)"
                :placeholder="variable.mime_type ? undefined : t('nativeProcesses.variables.anyMime')"
                :error="Boolean(variable.mime_type) && !mimeTypePattern.test(variable.mime_type!)" :error-message="t('nativeProcesses.variables.invalidMime')"
                @update:model-value="setConstraint(index, 'mime_type', $event)" />
            </template>
          </td>
          <td class="nullable-column"><q-toggle :model-value="variable.nullable" :disable="readonly" dense
            :aria-label="t('nativeProcesses.variables.nullable')" @update:model-value="update(index, { nullable: Boolean($event) })" /></td>
          <td><q-input :model-value="drafts[index] ?? (variable.default === undefined ? '' : JSON.stringify(variable.default.value))"
            outlined dense hide-bottom-space autogrow type="textarea" :readonly="readonly"
            :aria-label="t('nativeProcesses.variables.defaultJson')" :placeholder="t('nativeProcesses.variables.noDefault')"
            :error="Boolean(invalid[index])" :error-message="t('nativeProcesses.variables.invalidDefault')" @update:model-value="setDefault(index, String($event ?? ''))" /></td>
          <td v-if="$slots.usage"><slot name="usage" :variable="variable" /></td>
          <td v-if="!readonly" class="actions-column"><q-btn flat round dense color="negative" icon="delete_outline" :aria-label="t('nativeProcesses.variables.remove', { name: variable.name })" @click="remove(index)" /></td>
        </tr></tbody>
      </table>
    </div>
    <q-btn v-if="!readonly" outline dense no-caps size="sm" color="primary" icon="add" class="q-px-sm"
      :label="t('nativeProcesses.variables.add')" @click="add" />
  </section>
</template>
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { valueTypes, type ValueType, type ProcessVariable, type JsonValue } from '../services/nativeProcessService'
import { mimeTypes, mimeTypePattern, integerReferenceTypes, hiddenValueTypes } from '../variableTypes'
const props = defineProps<{ modelValue: ProcessVariable[]; label: string; readonly?: boolean; draftValues?: Record<number, string> }>()
const emit = defineEmits<{ 'update:modelValue': [value: ProcessVariable[]]; 'update:draftValues': [value: Record<number, string>]; validity: [valid: boolean] }>()
const { t } = useI18n()
const typeSearch = ref(''), mimeSearch = ref('')
const typeOptions = computed(() => valueTypes.filter(value => !hiddenValueTypes.includes(value)).map(value => ({ value, label: t(`nativeProcesses.variables.types.${value}`) }))
  .filter(option => `${option.label} ${option.value}`.toLocaleLowerCase().includes(typeSearch.value.toLocaleLowerCase())))
const documentOptions = computed(() => ['text', 'data'].map(value => ({ value, label: t(`documents.types.${value}`) })))
const mimeOptions = computed(() => mimeTypes.map(([value, key]) => ({ value, label: `${t(`nativeProcesses.variables.mimes.${key}`)} (${value})` }))
  .filter(option => option.label.toLocaleLowerCase().includes(mimeSearch.value.toLocaleLowerCase())))
function filterTypes(value: string, updateOptions: (callback: () => void) => void): void { updateOptions(() => { typeSearch.value = value }) }
function filterMimes(value: string, updateOptions: (callback: () => void) => void): void { updateOptions(() => { mimeSearch.value = value }) }
function mimeLabel(value?: string): string | undefined {
  const option = mimeTypes.find(([mime]) => mime === value)
  return option ? t(`nativeProcesses.variables.mimes.${option[1]}`) : value
}
const drafts = ref<Record<number, string>>({ ...props.draftValues }), invalid = ref<Record<number, boolean>>({})
const nameDrafts = ref<Record<number, string>>({})
const drag = ref<{ pointerId: number; from: number; to: number | null; startY: number; moved: boolean; handle: HTMLElement; table: HTMLTableElement } | null>(null)
for (const [index, value] of Object.entries(drafts.value)) { if (value.trim()) { try { JSON.parse(value) } catch { invalid.value[Number(index)] = true } } }
watch(drafts, value => emit('update:draftValues', { ...value }), { deep: true })
function initial(type: ValueType): JsonValue { return type === 'array' ? [] : type === 'object' ? {} : type === 'bool' ? false : ['int', 'float', ...integerReferenceTypes].includes(type) ? 1 : '' }
function update(index: number, value: Partial<ProcessVariable>): void {
  emit('update:modelValue', props.modelValue.map((variable, at) => at === index ? { ...variable, ...value } : variable))
}
function validName(index: number): boolean {
  const name = nameDrafts.value[index] ?? props.modelValue[index]?.name ?? ''
  return Boolean(name.trim()) && name === name.trim() && !props.modelValue.some((variable, at) => at !== index && variable.name === name)
}
function setName(index: number, name: string): void {
  nameDrafts.value[index] = name
  if (validName(index)) update(index, { name })
}
function add(): void { emit('update:modelValue', [...props.modelValue, { name: '', type: 'string', nullable: true }]) }
function applyOrder(order: number[]): void {
  const nextDrafts: Record<number, string> = {}, nextInvalid: Record<number, boolean> = {}, nextNames: Record<number, string> = {}
  order.forEach((previous, index) => {
    if (previous in drafts.value) nextDrafts[index] = drafts.value[previous]!
    if (previous in invalid.value) nextInvalid[index] = invalid.value[previous]!
    if (previous in nameDrafts.value) nextNames[index] = nameDrafts.value[previous]!
  })
  drafts.value = nextDrafts; invalid.value = nextInvalid; nameDrafts.value = nextNames
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
function changeType(index: number, value: ValueType): void {
  delete drafts.value[index]; delete invalid.value[index]
  emit('update:modelValue', props.modelValue.map((variable, at) => {
    if (at !== index) return variable
    const next = { ...variable, type: value }
    delete next.document_type; delete next.mime_type; delete next.default
    if (variable.default !== undefined && ['int', 'float', 'bool', 'string', 'array', 'object', ...integerReferenceTypes].includes(value))
      next.default = { type: value, value: initial(value) }
    return next
  }))
}
function setConstraint(index: number, key: 'document_type' | 'mime_type', value: string | null): void {
  emit('update:modelValue', props.modelValue.map((variable, at) => {
    if (at !== index) return variable
    const next = { ...variable }
    if (value) Object.assign(next, { [key]: value }); else delete next[key]
    return next
  }))
}
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
watch(() => [props.modelValue, invalid.value, nameDrafts.value], () => emit('validity', !Object.values(invalid.value).some(Boolean)
  && props.modelValue.every((variable, index) => validName(index) && (!variable.mime_type || mimeTypePattern.test(variable.mime_type)))), { immediate: true, deep: true })
</script>
<style scoped>
.variable-table { overflow-x: auto; border: 1px solid var(--q-separator-color, rgba(128, 128, 128, .24)); border-radius: 8px; }
table { width: 100%; min-width: 680px; border-collapse: collapse; table-layout: fixed; }
th { text-align: left; font-size: 12px; font-weight: 500; }
th, td { padding: 3px 4px; vertical-align: middle; }
tbody tr { border-top: 1px solid var(--q-separator-color, rgba(128, 128, 128, .24)); }
.name-column { width: 25%; }
.type-column { width: 28%; }
.drag-column { width: 30px; padding-left: 0; padding-right: 0; text-align: center; }
.drag-handle { cursor: grab; touch-action: none; }
.drag-handle:active { cursor: grabbing; }
.drop-before { box-shadow: inset 0 2px var(--solaire-blue-accent); }
.drop-after { box-shadow: inset 0 -2px var(--solaire-blue-accent); }
.nullable-column { width: 76px; text-align: center; }
.actions-column { width: 42px; text-align: center; }
.usage-column { width: 30%; }
table.with-usage { min-width: 1100px; }
.with-usage .name-column { width: 18%; }
.with-usage .type-column { width: 22%; }
.variable-table :deep(td > .q-field--dense .q-field__control) { height: 30px; min-height: 30px; padding: 0 6px; }
.variable-table :deep(td > .q-field--dense .q-field__marginal) { height: 30px; }
.variable-table :deep(td > .q-field--dense .q-field__native) { min-height: 30px; padding: 2px 0; }
.variable-table :deep(.q-textarea.q-field--dense .q-field__control) { height: auto; }
.variable-table :deep(.q-textarea .q-field__control-container) { padding: 0; }
.variable-table :deep(.q-textarea.q-field--dense .q-field__native) { padding: 6px 0; }
</style>
