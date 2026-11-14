<template>
  <q-select ref="select" v-model="model" :options="options" :label="label" outlined dense behavior="menu"
    @popup-show="open" @popup-hide="setQuery('')">
    <template #before-options>
      <q-input ref="search" :model-value="query" outlined dense autofocus clearable :label="t('common.search')" class="q-ma-sm"
        @update:model-value="value => setQuery(String(value ?? ''))" @keydown="searchKeydown">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
    </template>
    <template #no-option>
      <q-input ref="search" :model-value="query" outlined dense autofocus clearable :label="t('common.search')" class="q-ma-sm"
        @update:model-value="value => setQuery(String(value ?? ''))" @keydown="searchKeydown">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <q-item><q-item-section>{{ t('common.noData') }}</q-item-section></q-item>
    </template>
  </q-select>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QInput, QSelect } from 'quasar'

const { label } = defineProps<{ label: string }>()
const model = defineModel<string>({ required: true })
const { t } = useI18n()
const query = ref('')
const select = useTemplateRef<QSelect>('select')
const search = useTemplateRef<QInput>('search')
const options = computed(() => [...new Set([model.value, 'UTC', ...Intl.supportedValuesOf('timeZone')])]
  .filter(zone => zone.toLowerCase().includes(query.value.trim().toLowerCase())))

function setQuery(value: string): void {
  query.value = value
  select.value?.setOptionIndex(-1)
}
function open(): void {
  setQuery('')
  void nextTick(() => search.value?.focus())
}
function searchKeydown(event: KeyboardEvent): void {
  if (event.isComposing) return
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    event.stopPropagation()
    select.value?.moveOptionSelection(event.key === 'ArrowDown' ? 1 : -1)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    event.stopPropagation()
    const index = select.value?.getOptionIndex() ?? -1
    const option = options.value[index >= 0 ? index : 0]
    if (option) {
      model.value = option
      select.value?.hidePopup()
    }
  } else if (event.key !== 'Escape' && event.key !== 'Tab') {
    event.stopPropagation()
  }
}
</script>
