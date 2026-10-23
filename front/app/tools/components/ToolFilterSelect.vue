<template>
  <q-select v-model="model" :options="options" :label="label" clearable dense outlined emit-value map-options>
    <template #option="scope">
      <q-item-label v-if="scope.opt.header" header role="presentation" class="text-weight-medium">
        {{ scope.opt.label }}
      </q-item-label>
      <q-item v-else v-bind="scope.itemProps">
        <q-item-section>{{ scope.opt.label }}</q-item-section>
      </q-item>
    </template>
  </q-select>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { toolMessageKey, toolOrigin, type ToolOrigin } from '../presentation'
import type { Tool } from '../services/toolService'

const model = defineModel<number | null>({ required: true })
const props = defineProps<{ tools: Tool[]; label: string }>()
const { t } = useI18n()

const options = computed(() => (['galaris', 'custom'] as const).flatMap((origin: ToolOrigin) => {
  const tools = props.tools.filter(tool => toolOrigin(tool) === origin)
  if (!tools.length) return []
  return [
    { label: t(`tools.origins.${origin}`), value: origin, disable: true, header: true },
    ...tools.map(tool => {
      const key = toolMessageKey(tool.code, 'label')
      const label = key && (!tool.can_edit || tool.label === t(key, {}, { locale: 'en' })) ? t(key) : tool.label
      return { label, value: tool.id, disable: false, header: false }
    }),
  ]
}))
</script>
