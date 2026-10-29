<template>
  <q-btn flat round dense size="sm" color="primary" icon="short_text"
    :aria-label="t('resourceSummary.open')" @click="open = true">
    <q-tooltip>{{ t('resourceSummary.open') }}</q-tooltip>
  </q-btn>
  <q-dialog v-model="open" :aria-label="t('resourceSummary.title')">
    <q-card class="galaris-dialog-card column no-wrap" style="width: 560px; max-width: 95vw">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6">{{ t('resourceSummary.title') }}</div>
        <q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('resourceSummary.close')" />
      </q-card-section>
      <q-card-section class="galaris-dialog-body scroll">
        <div class="text-subtitle2 q-mb-md">{{ title }}</div>
        <div v-if="loading" role="status" class="row justify-center q-pa-md">
          <q-spinner color="primary" size="28px" :aria-label="t('resourceSummary.loading')" />
        </div>
        <q-banner v-else-if="error" role="alert">
          {{ t('resourceSummary.error') }}
          <template #action>
            <q-btn outline color="primary" :label="t('resourceSummary.retry')" @click="reload" />
          </template>
        </q-banner>
        <template v-else-if="summary">
          <EditorialContent v-if="hasContent" :content="summary.content" :media-type="summary.mediaType" profile="rich-text" />
          <div v-else class="text-body2 text-grey-7">{{ t('resourceSummary.empty') }}</div>
          <div v-if="summary.keywords.length" class="q-mt-md">
            <div class="text-caption q-mb-xs">{{ t('resourceSummary.keywords') }}</div>
            <div class="row q-gutter-xs">
              <q-chip v-for="keyword in summary.keywords" :key="keyword" dense>{{ keyword }}</q-chip>
            </div>
          </div>
        </template>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { defineAsyncView } from '../asyncView'
import { richTextExcerpt } from '../richText'
import type { ResourceSummaryView } from '../resourceSummary'

const EditorialContent = defineAsyncView(() => import('./EditorialContent.vue'))
const props = defineProps<{
  resourceKey: string
  title: string
  load: (signal: AbortSignal) => Promise<ResourceSummaryView>
}>()
const { t } = useI18n()
const open = ref(false), loading = ref(false), error = ref(false)
const summary = shallowRef<ResourceSummaryView>()
let controller: AbortController | undefined
let generation = 0
const hasContent = computed(() => {
  const value = summary.value
  return !!value && !!(value.mediaType === 'text/html' ? richTextExcerpt(value.content) : value.content.trim())
})

function clear(): void {
  generation++
  controller?.abort()
  controller = undefined
  summary.value = undefined
  loading.value = false
  error.value = false
}
async function reload(): Promise<void> {
  clear()
  const request = generation
  const active = new AbortController()
  controller = active
  loading.value = true
  try {
    const result = await props.load(active.signal)
    if (request === generation && open.value && !active.signal.aborted) summary.value = result
  } catch {
    if (request === generation && open.value && !active.signal.aborted) error.value = true
  } finally {
    if (request === generation) loading.value = false
  }
}
watch(open, visible => { if (visible) void reload(); else clear() })
watch(() => props.resourceKey, () => { open.value = false; clear() }, { flush: 'sync' })
onBeforeUnmount(clear)
</script>
