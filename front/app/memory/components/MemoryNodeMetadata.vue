<template>
  <dl class="memory-node-metadata row q-col-gutter-sm q-ma-none">
    <div class="col-12 col-sm-6">
      <dt class="text-caption text-grey-7">{{ t('memory.kind') }}</dt>
      <dd>{{ roleLabel }}</dd>
    </div>
    <div class="col-12 col-sm-6">
      <dt class="text-caption text-grey-7">{{ t('memory.visibility') }}</dt>
      <dd>{{ t(`memory.visibilities.${node.visibility}`) }}</dd>
    </div>
    <div class="col-12 col-sm-6">
      <dt class="text-caption text-grey-7">{{ t('memory.graph.lastActivity') }}</dt>
      <dd>{{ activityDate }}</dd>
    </div>
    <div class="col-12 col-sm-6">
      <dt class="text-caption text-grey-7">{{ t('memory.accessCount') }}</dt>
      <dd>{{ new Intl.NumberFormat(locale).format(node.access_count) }}</dd>
    </div>
  </dl>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { MemoryGraphNode } from '../types'

const { node, roleLabel } = defineProps<{
  node: Pick<MemoryGraphNode, 'visibility' | 'activity_at' | 'access_count'>
  roleLabel: string
}>()
const { t, locale } = useI18n()
const activityDate = computed(() => {
  const timestamp = Date.parse(node.activity_at)
  return Number.isFinite(timestamp)
    ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(timestamp)
    : '—'
})
</script>

<style scoped>
.memory-node-metadata dd { margin: 0; overflow-wrap: anywhere; }
</style>
