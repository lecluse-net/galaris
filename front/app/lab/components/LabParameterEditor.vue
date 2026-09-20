<template>
  <div class="parameter-editor">
    <div v-if="fields.length > 6" class="parameter-tools">
      <q-input v-model="search" dense outlined clearable :label="t('evaluation.contract.parameterSearch')" class="parameter-search">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <q-btn flat dense no-caps :label="t('evaluation.contract.expandParameters')" @click="expandAll" />
      <q-btn flat dense no-caps :label="t('evaluation.contract.collapseParameters')" @click="collapseAll" />
    </div>
    <div v-if="query && !matchingFields.length" class="text-grey-7 q-pa-md" role="status">{{ t('evaluation.contract.noParameters') }}</div>
    <q-expansion-item
      v-for="(group, index) in groups" v-show="group.fields.some(matches)" :key="group.key"
      :model-value="query ? true : (expanded[group.key] ?? index === 0)"
      :icon="group.icon" :label="t(`evaluation.contract.parameterGroups.${group.key}`)"
      :caption="groupCaption(group)" class="parameter-section" header-class="parameter-section-header"
      @update:model-value="expanded[group.key] = $event"
    >
      <div class="parameter-grid q-pa-md">
        <div
          v-for="field in group.fields" v-show="matches(field)" :key="field.name"
          class="parameter-field" :class="{ 'parameter-field--wide': field.structured || field.multiline }"
          :data-parameter="field.name"
        >
          <q-expansion-item
            v-if="field.structured" :label="field.label" :caption="errors[field.name] ? t('evaluation.contract.invalidJson') : summary(value(field.name))"
            :icon="field.schema.type === 'array' ? 'format_list_bulleted' : 'data_object'"
            :header-class="errors[field.name] ? 'text-negative' : ''" class="parameter-object"
          >
            <div class="q-pa-md q-pt-none">
              <LabValueEditor :model-value="value(field.name)" :schema="field.schema" :label="field.label" :readonly="readonly" compact @update:model-value="set(field.name, $event)" @invalid="setInvalid(field.name, $event)" />
            </div>
          </q-expansion-item>
          <LabValueEditor
            v-else :model-value="value(field.name)" :schema="field.schema" :label="field.label"
            :readonly="readonly" :multiline="field.multiline" :nullable="field.nullable" compact
            @update:model-value="set(field.name, $event)" @invalid="setInvalid(field.name, $event)"
          />
        </div>
      </div>
    </q-expansion-item>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import LabValueEditor from './LabValueEditor.vue'
import { isMultilineParameter, isStructuredParameter, parameterGroups, resolveParameterSchema } from '../parameterPresentation'
import type { JsonSchema } from '../services/labWorkbenchService'
const { modelValue, schema, defaults = {}, readonly = false } = defineProps<{
  modelValue: Record<string, unknown>; schema: JsonSchema; defaults?: Record<string, unknown>; readonly?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, unknown>]; invalid: [value: boolean] }>()
const { t, te } = useI18n()
const errors = ref<Record<string, boolean>>({})
const expanded = ref<Record<string, boolean>>({})
const search = ref<string | null>('')
const normalize = (value: string) => value.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLocaleLowerCase()
const query = computed(() => normalize(search.value?.trim() ?? ''))
const fields = computed(() => Object.entries(schema.properties ?? {}).flatMap(([name, field]) => {
  const resolved = resolveParameterSchema(field, schema)
  if (resolved.const !== undefined) return []
  return [{ name, schema: resolved, nullable: field.anyOf?.some(item => item.type === 'null') ?? false, label: fieldLabel(name), structured: isStructuredParameter(resolved), multiline: isMultilineParameter(name) }]
}))
type ParameterField = (typeof fields.value)[number]
const groups = computed(() => parameterGroups.map(group => ({
  ...group,
  fields: fields.value.filter(field => (parameterGroups.find(candidate => candidate.fields.some(name => name === field.name))?.key ?? 'context') === group.key),
})).filter(group => group.fields.length))
const matchingFields = computed(() => fields.value.filter(matches))

function fieldLabel(name: string) { const key = `evaluation.contract.fields.${name}`; return te(key) ? t(key) : t('evaluation.contract.namedField', { name }) }
function matches(field: ParameterField) { return !query.value || normalize(`${field.label} ${field.name}`).includes(query.value) }
function value(name: string): unknown {
  if (Object.hasOwn(modelValue, name)) return modelValue[name]
  if (Object.hasOwn(defaults, name)) return defaults[name]
  return fields.value.find(field => field.name === name)?.schema.default
}
function summary(value: unknown): string {
  if (value == null) return t('evaluation.contract.parameterEmpty')
  if (Array.isArray(value)) return t('evaluation.contract.parameterEntries', { count: value.length })
  if (typeof value === 'object') {
    const preview = Object.values(value).filter((item): item is string => typeof item === 'string' && Boolean(item.trim())).slice(0, 2).join(' · ').slice(0, 100)
    return preview || t('evaluation.contract.parameterProperties', { count: Object.keys(value).length })
  }
  return String(value).slice(0, 100)
}
function groupCaption(group: (typeof groups.value)[number]): string {
  const count = group.fields.filter(matches).length
  const invalid = group.fields.filter(field => errors.value[field.name]).length
  return invalid ? t('evaluation.contract.parameterErrors', { count: invalid }) : t('evaluation.contract.parameterCount', { count })
}
function expandAll() { search.value = ''; expanded.value = Object.fromEntries(groups.value.map(group => [group.key, true])) }
function collapseAll() { search.value = ''; expanded.value = Object.fromEntries(groups.value.map(group => [group.key, false])) }
function set(name: string, value: unknown) { emit('update:modelValue', { ...modelValue, [name]: value }) }
function setInvalid(name: string, value: boolean) { errors.value[name] = value; emit('invalid', Object.values(errors.value).some(Boolean)) }
watch(() => schema, () => { search.value = ''; expanded.value = {}; errors.value = {}; emit('invalid', false) })
</script>

<style scoped>
.parameter-editor { display: grid; gap: 12px; }
.parameter-tools { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.parameter-search { flex: 1 1 280px; }
.parameter-section { border: 1px solid rgba(127, 127, 127, 0.25); border-radius: 10px; overflow: hidden; }
.parameter-section :deep(.parameter-section-header) { min-height: 68px; background: rgba(127, 127, 127, 0.04); }
.parameter-section :deep(.parameter-section-header .q-item__label:not(.q-item__label--caption)) { font-weight: 600; }
.parameter-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; align-items: start; }
.parameter-field { min-width: 0; }
.parameter-field--wide { grid-column: 1 / -1; }
.parameter-object { border: 1px solid rgba(127, 127, 127, 0.2); border-radius: 8px; }
.parameter-object :deep(.q-item__label) { overflow-wrap: anywhere; }
@media (max-width: 1023px) { .parameter-search { flex-basis: 100%; } }
@media (min-width: 1024px) { .parameter-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
