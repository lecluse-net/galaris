<template>
  <q-select v-if="resolved.enum" :model-value="modelValue" :options="resolved.enum" :clearable="nullable || schema.anyOf?.some(item => item.type === 'null')" :label="label" outlined :dense="compact" :readonly="readonly" @update:model-value="update" />
  <q-toggle v-else-if="resolved.type === 'boolean'" :model-value="Boolean(modelValue)" :label="label" :disable="readonly" @update:model-value="update" />
  <q-input v-else-if="resolved.type === 'integer' || resolved.type === 'number'" :model-value="numericValue" type="number" :min="resolved.minimum" :max="resolved.maximum" :label="label" outlined :dense="compact" :readonly="readonly" @update:model-value="numeric" />
  <q-input v-else-if="resolved.type === 'string'" :model-value="modelValue == null ? '' : String(modelValue)" :type="multiline ? 'textarea' : 'text'" :autogrow="multiline && !compact" :rows="4" :label="label" outlined :dense="compact" :readonly="readonly" @update:model-value="update" />
  <div v-else>
    <JsonEditor :model-value="json" :label="label" language="json" :readonly="readonly" :visible-lines="6" @update:model-value="parse" />
    <div v-if="invalid" class="text-negative text-caption">{{ t('evaluation.contract.invalidJson') }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { JsonEditor } from '@/core/util'
import type { JsonSchema } from '../services/labWorkbenchService'
const { modelValue, schema, label, readonly = false, compact = false, multiline = true, nullable = false } = defineProps<{ modelValue: unknown; schema: JsonSchema; label: string; readonly?: boolean; compact?: boolean; multiline?: boolean; nullable?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: unknown]; invalid: [value: boolean] }>()
const { t } = useI18n()
const json = ref('')
const invalid = ref(false)
const numericValue = computed(() => typeof modelValue === 'number' ? modelValue : null)
const resolved = computed(() => schema.anyOf?.find(item => item.type !== 'null') ?? schema)
watch(() => modelValue, value => { json.value = JSON.stringify(value ?? null, null, 2); invalid.value = false; emit('invalid', false) }, { immediate: true })
function update(value: unknown) { emit('update:modelValue', value); emit('invalid', false) }
function numeric(value: string | number | null) { update(value === '' || value === null ? null : Number(value)) }
function parse(value: string) {
  json.value = value
  try { const parsed: unknown = JSON.parse(value); invalid.value = false; update(parsed) }
  catch { invalid.value = true; emit('invalid', true) }
}
</script>
