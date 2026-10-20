<template>
  <ActionContextMenu :target="target" :actions="actions" />
  <ResourceDetailDialog v-if="detail" :target="detail" @close="detail = null" />
</template>
<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import ActionContextMenu from './ActionContextMenu.vue'
import { richLinkTarget } from '../richText'
import { useResourceCopy } from '../resourceCopy'
import { ResourceDetailDialog, type ResourceDetailTarget } from '../resourceDetail'
const { uri, title = '', target } = defineProps<{ uri: string; title?: string; target: string }>()
const { t } = useI18n(), { action } = useResourceCopy()
const detail = shallowRef<ResourceDetailTarget | null>(null)
const actions = computed(() => [
  { key: 'open', icon: 'visibility', label: t('common.open'), run: () => { detail.value = richLinkTarget(uri, title) } },
  action(uri),
])
</script>
