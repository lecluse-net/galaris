<template>
  <q-select
    :model-value="model"
    :options="choices"
    emit-value map-options
    @update:model-value="selectParameter"
  >
    <template #option="{ itemProps, opt }">
      <q-item v-bind="itemProps">
        <q-item-section v-if="opt.value === newParameter" avatar>
          <q-icon name="add" color="primary" />
        </q-item-section>
        <q-item-section>{{ opt.label }}</q-item-section>
      </q-item>
    </template>
  </q-select>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const model = defineModel<string>({ default: '' })
const props = defineProps<{
  options: string[]
  createParameter: () => string
}>()
const { t } = useI18n()
const newParameter = Symbol('newConnectionParameter')
const choices = computed(() => [
  ...props.options.map(name => ({ label: name, value: name })),
  { label: t('tools.newParam'), value: newParameter },
])

function selectParameter(value: unknown) {
  if (value === newParameter) model.value = props.createParameter()
  else model.value = typeof value === 'string' ? value : ''
}
</script>
