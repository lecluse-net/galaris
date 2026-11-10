<template>
  <q-input ref="input" :model-value="model" outlined dense autofocus clearable :label="t('agent.searchByName')" class="q-ma-sm"
    @update:model-value="value => { model = String(value ?? '') }">
    <template #prepend><q-icon name="search" /></template>
  </q-input>
</template>

<script setup lang="ts">
import { useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QInput } from 'quasar'

const model = defineModel<string>({ required: true })
const { t } = useI18n()
const input = useTemplateRef<QInput>('input')
defineExpose({ focus: () => input.value?.focus() })
</script>
