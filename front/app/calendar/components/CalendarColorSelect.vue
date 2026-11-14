<template>
  <q-select :model-value="modelValue" :options="options" outlined dense emit-value map-options
    :label="t('agenda.color')" @update:model-value="emit('update:modelValue', $event)">
    <template #prepend><q-icon name="circle" :style="{ color: solaireCss[modelValue].accent }" /></template>
    <template #option="scope"><q-item v-bind="scope.itemProps">
      <q-item-section avatar><q-icon name="circle" :style="{ color: solaireCss[scope.opt.value as SolaireColor].accent }" /></q-item-section>
      <q-item-section>{{ scope.opt.label }}</q-item-section>
    </q-item></template>
  </q-select>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { solaireColors, solaireCss, type SolaireColor } from '@/core/util'
defineProps<{ modelValue: SolaireColor }>()
const emit = defineEmits<{ 'update:modelValue': [color: SolaireColor] }>()
const { t } = useI18n()
const options = computed(() => solaireColors.map(value => ({ value, label: t(`agenda.colors.${value}`) })))
</script>
