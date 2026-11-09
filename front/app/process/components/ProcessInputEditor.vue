<template>
  <q-dialog :model-value="true" @update:model-value="emit('close')">
    <q-card class="galaris-dialog-card input-editor">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6 ellipsis">{{ t('nativeProcesses.inputs.edit', { name: variable.label || variable.name }) }}</div>
        <q-space /><q-btn flat round dense icon="close" :aria-label="t('common.close')" @click="emit('close')" />
      </q-card-section>
      <q-form @submit="save">
        <q-card-section class="q-gutter-y-md">
          <div>{{ variable.description }}</div>
          <q-banner v-if="error" role="alert">{{ error }}</q-banner>
          <q-checkbox v-if="variable.nullable" v-model="explicitNull" :disable="busy" :label="t('nativeProcesses.inputs.explicitNull')" />
          <template v-if="!explicitNull">
            <q-select v-if="variable.type === 'bool'" v-model="booleanValue" outlined emit-value map-options :options="booleanOptions"
              :disable="busy" :label="variable.label || variable.name" />
            <q-input v-else v-model="text" outlined :type="inputType" :stack-label="variable.type === 'date'" :disable="busy || Boolean(file)"
              :label="variable.label || variable.name" :hint="hint" :autogrow="['array', 'object', 'string'].includes(variable.type)" />
            <q-file v-if="variable.type === 'File'" v-model="file" outlined clearable :disable="busy" :accept="variable.mime_type"
              :label="t('nativeProcesses.inputs.upload')"><template #prepend><q-icon name="attach_file" /></template></q-file>
          </template>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn outline color="primary" :label="t('common.cancel')" @click="emit('close')" />
          <q-btn type="submit" color="primary" :loading="busy" :label="t('nativeProcesses.inputs.save')" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { nativeProcessService as service, type ProcessVariable } from '../services/nativeProcessService'
import { integerReferenceTypes } from '../variableTypes'
const props = defineProps<{ runId: string; variable: ProcessVariable; value: unknown; revision: number }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const { t } = useI18n()
const expectedRevision = props.revision
const initial = props.value && typeof props.value === 'object' && 'value' in props.value ? props.value.value : undefined
const explicitNull = ref(initial === null), booleanValue = ref<boolean | null>(typeof initial === 'boolean' ? initial : null)
// Arrays/objects are displayed as ordinary JSON, not the transport's nested envelopes.
function plain(value: unknown): unknown {
  if (!value || typeof value !== 'object') return value
  if ('type' in value && typeof value.type === 'string' && 'value' in value) return plain(value.value)
  return Array.isArray(value) ? value.map(plain) : Object.fromEntries(Object.entries(value).map(([name, entry]) => [name, plain(entry)]))
}
const text = ref(initial == null ? '' : typeof initial === 'string' ? initial : JSON.stringify(plain(initial)))
const file = ref<File | null>(null), busy = ref(false), error = ref('')
const controller = new AbortController()
onBeforeUnmount(() => controller.abort())
const booleanOptions = computed(() => [{ label: t('nativeProcesses.inputs.true'), value: true }, { label: t('nativeProcesses.inputs.false'), value: false }])
const inputType = computed(() => props.variable.type === 'date' ? 'date' : ['array', 'object', 'string'].includes(props.variable.type) ? 'textarea' : 'text')
const hint = computed(() => props.variable.type === 'datetime' ? t('nativeProcesses.variables.datetimeHint')
  : ['File', 'Document'].includes(props.variable.type) ? t('nativeProcesses.inputs.uri')
  : ['array', 'object'].includes(props.variable.type) ? t('nativeProcesses.inputs.json') : '')
function value(): unknown {
  if (explicitNull.value) return null
  if (props.variable.type === 'bool') { if (booleanValue.value === null) throw new Error(); return booleanValue.value }
  if (['array', 'object'].includes(props.variable.type)) return JSON.parse(text.value)
  if (['int', 'float', ...integerReferenceTypes].includes(props.variable.type)) {
    if (!text.value.trim()) throw new Error()
    const result = Number(text.value)
    if (!Number.isFinite(result) || props.variable.type !== 'float' && !Number.isSafeInteger(result)) throw new Error()
    return result
  }
  return text.value
}
async function save(): Promise<void> {
  if (busy.value) return
  error.value = ''; busy.value = true
  try {
    if (file.value && !explicitNull.value) await service.uploadInput(props.runId, props.variable.name, file.value, expectedRevision, controller.signal)
    else {
      let selected: unknown
      try { selected = value() } catch { error.value = t('nativeProcesses.inputs.invalid'); return }
      await service.contributeInputs(props.runId, { [props.variable.name]: selected }, expectedRevision, false, controller.signal)
    }
    if (!controller.signal.aborted) emit('saved')
  } catch { if (!controller.signal.aborted) error.value = t('nativeProcesses.inputs.failed') }
  finally { busy.value = false }
}
</script>
<style scoped>
.input-editor { width: 600px; max-width: 95vw; }
</style>
