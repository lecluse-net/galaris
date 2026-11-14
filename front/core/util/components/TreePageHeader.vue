<template>
  <div class="row items-center no-wrap full-width tree-page-header" :title="titles ? t('common.treePageNames', { first: titles.first_title, last: titles.last_title }) : numericLabel">
    <q-icon name="folder_zip" size="26px" class="q-mr-xs tree-page-icon" />
    <i18n-t v-if="titles" keypath="common.treePageNames" tag="span" class="tree-page-names">
      <template #first><span class="ellipsis tree-page-name">{{ titles.first_title }}</span></template>
      <template #last><span class="ellipsis tree-page-name">{{ titles.last_title }}</span></template>
    </i18n-t>
    <span v-else>{{ numericLabel }}</span>
    <q-spinner v-if="loading" color="primary" size="16px" class="q-ml-sm" />
  </div>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { computed } from 'vue'
import type { TreePage } from '../treePages'
const props = defineProps<{ page: TreePage; total: number; loading?: boolean; titles?: { first_title: string; last_title: string } }>()
const { t } = useI18n()
const numericLabel = computed(() => t('common.treePage', { first: props.page.offset + 1, last: Math.min(props.total, props.page.offset + props.page.size) }))
</script>
<style scoped>
.tree-page-icon { color: var(--solaire-cyan-accent); }
.tree-page-header { min-width: 0; }
.tree-page-names { display: grid; grid-template-columns: minmax(0, max-content) auto minmax(0, max-content); align-items: center; gap: 4px; flex: 0 1 auto; min-width: 0; white-space: pre; }
.tree-page-name { min-width: 0; }
</style>
