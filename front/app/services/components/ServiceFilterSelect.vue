<template>
  <q-select v-model="model" :options="options" :label="label"
    :clearable="clearable" :dense="dense" :filled="filled" :outlined="!filled" emit-value map-options>
    <template #option="scope">
      <q-item-label v-if="scope.opt.header" header role="presentation" class="text-weight-medium">
        {{ scope.opt.label }}
      </q-item-label>
      <q-item v-else v-bind="scope.itemProps">
        <q-item-section avatar><ServiceIdentityIcon :service="scope.opt.service" /></q-item-section>
        <q-item-section>{{ scope.opt.label }}</q-item-section>
        <q-item-section v-if="showOrigin" side><ServiceOriginBadge :tool="scope.opt.service" /></q-item-section>
      </q-item>
    </template>
    <template #selected-item="scope">
      <span class="row items-center no-wrap service-selected-item">
        <ServiceIdentityIcon :service="scope.opt.service" :size="20" class="q-mr-sm" />
        <span class="ellipsis">{{ scope.opt.label }}</span>
        <ServiceOriginBadge v-if="showOrigin" :tool="scope.opt.service" class="q-ml-sm" />
      </span>
    </template>
  </q-select>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { SERVICE_ORIGINS, toolMessageKey, toolOrigin } from '../presentation'
import type { Service } from '../services/serviceApi'
import ServiceIdentityIcon from './ServiceIdentityIcon.vue'
import ServiceOriginBadge from './ServiceOriginBadge.vue'

const model = defineModel<number | null>({ required: true })
const { tools, label, clearable = true, dense = true, filled = false, showOrigin = false } = defineProps<{
  tools: (Pick<Service, 'id' | 'code' | 'label' | 'can_edit' | 'icon'> & { displayLabel?: string })[]
  label: string
  clearable?: boolean
  dense?: boolean
  filled?: boolean
  showOrigin?: boolean
}>()
const { t } = useI18n()

const options = computed(() => SERVICE_ORIGINS.flatMap(origin => {
  const originTools = tools.filter(tool => toolOrigin(tool) === origin)
  if (!originTools.length) return []
  return [
    { label: t(`services.origins.${origin}`), value: origin, disable: true, header: true, service: undefined },
    ...originTools.map(tool => {
      const key = toolMessageKey(tool.code, 'label')
      const label = key && (!tool.can_edit || tool.label === t(key, {}, { locale: 'en' })) ? t(key) : tool.label
      return { label: tool.displayLabel ?? label, value: tool.id, disable: false, header: false, service: tool }
    }),
  ]
}))
</script>
<style scoped>
.service-selected-item { min-width: 0; max-width: 100%; }
</style>
