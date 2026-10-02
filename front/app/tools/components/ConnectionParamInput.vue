<template>
  <q-select
    v-if="definition.options?.length"
    v-model="value"
    :options="choices"
    :label="label"
    :clearable="name !== 'tools.fileindexing'"
    emit-value map-options dense outlined
  />
  <q-select
    v-else-if="definition.type === 'user'"
    v-model="value"
    :options="userOptions"
    :loading="loadingUsers"
    :label="label"
    emit-value map-options clearable dense outlined
  />
  <q-toggle
    v-else-if="definition.type === 'boolean'"
    :model-value="value === 'true'"
    :label="label"
    color="primary"
    @update:model-value="value = $event ? 'true' : 'false'"
  />
  <q-input
    v-else
    v-model="value"
    :type="definition.type === 'password' ? 'password' : definition.type === 'integer' ? 'number' : 'text'"
    :label="label"
    :placeholder="placeholder ?? (definition.type === 'password' ? '' : String(definition.default ?? ''))"
    dense outlined
  >
    <template v-if="$slots.append" #append><slot name="append" /></template>
  </q-input>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ConnectionParamDef } from '../services/toolService'
import { connectionParamLabel, connectionParamOptions } from '../presentation'

const props = defineProps<{
  name: string
  toolCode?: string
  definition: Partial<ConnectionParamDef>
  placeholder?: string
  userOptions?: Array<{ value: string; label: string }>
  loadingUsers?: boolean
}>()
const value = defineModel<string | null>()
const { t, te } = useI18n()
const label = computed(() => {
  const title = connectionParamLabel(props.toolCode, props.name, props.definition, t, te)
  return props.definition.required ? `${title} *` : title
})
const choices = computed(() => connectionParamOptions(props.toolCode, props.name, props.definition, t, te))
</script>
