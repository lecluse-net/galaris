<template>
  <template v-if="total <= TREE_PAGE_SIZE && !within"><slot :data-key="parent" /></template>
  <template v-else>
    <q-expansion-item v-for="page in treePages(parent, total, within)" :key="treePageKey(page)" dense :duration="0"
      :model-value="expanded.includes(treePageKey(page))" @update:model-value="value => toggle(page, value)">
      <template #header><TreePageHeader :page="page" :total="total" :titles="ranges?.[within ? treePageKey(within) : parent]?.find(range => range.offset === page.offset && range.size === page.size)" :loading="loading[treePageDataKey(treePageKey(page))]" /></template>
      <q-banner v-if="expanded.includes(treePageKey(page)) && errors[treePageDataKey(treePageKey(page))]" dense role="alert">{{ t('common.viewLoadError') }}
        <q-btn outline dense color="primary" :label="t('common.retry')" @click="load(treePageKey(page))" />
      </q-banner>
      <TreePageGroups v-if="expanded.includes(treePageKey(page)) && page.size > TREE_PAGE_SIZE" :parent="parent" :total="total" :within="page" :load="load" :loading="loading" :errors="errors" :ranges="ranges" :expanded="expanded" @toggle="(key, open) => emit('toggle', key, open)">
        <template #default="scope"><slot :data-key="scope.dataKey" /></template>
      </TreePageGroups>
      <template v-else-if="expanded.includes(treePageKey(page))">
        <slot :data-key="treePageDataKey(treePageKey(page))" />
      </template>
    </q-expansion-item>
  </template>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { watch } from 'vue'
import TreePageHeader from './TreePageHeader.vue'
import { TREE_PAGE_SIZE, treePages, treePageKey, treePageDataKey, type TreePage } from '../treePages'
const props = defineProps<{
  parent: string; total: number; within?: TreePage
  load: (key: string) => Promise<void>
  loading: Record<string, boolean>; errors: Record<string, boolean>
  expanded: string[]
  ranges?: Record<string, { offset: number; size: number; first_title: string; last_title: string }[]>
}>()
const emit = defineEmits<{ toggle: [key: string, open: boolean] }>()
defineSlots<{ default(props: { dataKey: string }): unknown }>()
const { t } = useI18n()
function toggle(page: TreePage, open: boolean): void {
  const key = treePageKey(page)
  emit('toggle', key, open)
}
watch(() => [props.expanded, props.parent, props.total, props.within] as const, () => {
  for (const page of treePages(props.parent, props.total, props.within)) {
    const key = treePageKey(page)
    if (props.expanded.includes(key) && !props.errors[treePageDataKey(key)]) void props.load(key)
  }
}, { immediate: true })
</script>
