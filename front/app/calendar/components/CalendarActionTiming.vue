<template>
  <div class="q-gutter-y-sm">
    <q-select v-model="anchor" outlined dense emit-value map-options :label="t('agenda.anchor')" :options="anchors" :disable="disable" />
    <div class="row q-col-gutter-sm"><q-select :model-value="Math.sign(offset)" class="col" outlined dense emit-value map-options :label="t('agenda.timing')" :options="timings" :disable="disable" @update:model-value="offset = $event * (Math.abs(offset) || 10)" />
      <q-input v-if="offset !== 0" :model-value="Math.abs(offset)" class="col" type="number" outlined dense :min="1" :max="525600" :label="t('agenda.offset')" :rules="[validMinutes]" :disable="disable" @update:model-value="offset = Math.sign(offset) * Number($event)" /></div>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
defineProps<{ disable?: boolean }>()
const anchor = defineModel<'start' | 'end'>('anchor', { required: true })
const offset = defineModel<number>('offset', { required: true })
const { t } = useI18n()
const anchors = computed(() => ['start', 'end'].map(value => ({ value, label: t(`agenda.anchors.${value}`) })))
const timings = computed(() => [{ value: -1, label: t('agenda.before') }, { value: 0, label: t('agenda.atTime') }, { value: 1, label: t('agenda.after') }])
const validMinutes = (value: unknown) => Number.isInteger(Number(value)) && Number(value) > 0 && Number(value) <= 525600 || t('agenda.required')
</script>
