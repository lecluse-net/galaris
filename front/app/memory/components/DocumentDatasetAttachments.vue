<template>
  <section :aria-label="t('documents.datasetAttachments.title')" class="q-mt-md">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <div class="text-subtitle2">{{ t('documents.datasetAttachments.title') }}</div>
      <q-space />
      <q-btn v-if="editable" outline color="primary" icon="data_object" :label="t('documents.datasetAttachments.add')" :disable="busy || !state" @click="open" />
    </div>
    <q-banner v-if="error" role="alert">
      {{ error }} <q-btn outline :label="t('documents.retry')" :disable="busy" @click="load" />
    </q-banner>
    <q-spinner v-if="busy && !state" color="primary" />
    <q-list v-if="state?.items.length" bordered separator>
      <q-item v-for="item in state.items" :key="item.uri">
        <q-item-section avatar><q-icon name="data_object" /></q-item-section>
        <q-item-section>
          <router-link v-if="item.available" :to="href(item.uri)">{{ item.title }}</router-link>
          <q-item-label v-else>{{ t('documents.datasetAttachments.unavailable') }}</q-item-label>
          <q-item-label caption>{{ item.uri }}</q-item-label>
        </q-item-section>
        <q-item-section v-if="editable" side>
          <q-btn outline icon="link_off" :aria-label="t('documents.datasetAttachments.remove', { name: item.title ?? item.uri })" :disable="busy" @click="remove(item.uri)" />
        </q-item-section>
      </q-item>
    </q-list>
    <p v-else-if="state && !error" class="text-grey-7">{{ t('documents.datasetAttachments.empty') }}</p>
    <q-dialog v-model="adding">
      <q-card style="width: 520px; max-width: 95vw">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ t('documents.datasetAttachments.add') }}</div><q-space />
          <q-btn v-close-popup outline round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section>
          <p>{{ t('documents.datasetAttachments.hint') }}</p>
          <q-banner v-if="dialogError" role="alert" class="q-mb-sm">{{ dialogError }} <q-btn outline :label="t('documents.retry')" :disable="busy" @click="load" /></q-banner>
          <q-select v-model="selected" outlined use-input clearable emit-value map-options :options="options"
            :label="t('documents.datasetAttachments.select')" :loading="searching" input-debounce="250" @filter="filter" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup outline :label="t('common.cancel')" />
          <q-btn color="primary" :label="t('documents.datasetAttachments.attach')" :disable="!selected" :loading="busy" @click="attach" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </section>
</template>
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { searchRichLinks } from '@/core/util'
import { memoryService } from '../services/memoryService'
import type { DocumentDatasetAttachments } from '../types'

const props = defineProps<{ documentId: string; agentId: number | null; editable: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const { t } = useI18n()
const state = ref<DocumentDatasetAttachments>(), error = ref(''), dialogError = ref(''), busy = ref(false)
const adding = ref(false), selected = ref<string | null>(null), options = ref<{ value: string; label: string }[]>([]), searching = ref(false)
let active = true, searchGeneration = 0
const identity = (uri: string) => uri.slice('data://'.length)
const href = (uri: string) => `/dataset/${encodeURIComponent(identity(uri))}`
async function load(): Promise<void> {
  busy.value = true; error.value = ''; dialogError.value = ''
  try { const result = await memoryService.documentDatasets(props.documentId, props.agentId); if (active) state.value = result }
  catch { if (active) error.value = t('documents.datasetAttachments.error') }
  finally { if (active) busy.value = false }
}
function open(): void { selected.value = null; dialogError.value = ''; adding.value = true }
async function filter(query: string, update: (callback: () => void) => void): Promise<void> {
  const generation = ++searchGeneration
  searching.value = true
  try {
    const targets = await searchRichLinks(query, 'data')
    if (!active || generation !== searchGeneration) return
    update(() => { options.value = targets.filter(item => item.uri.startsWith('data://')).map(item => ({ value: identity(item.uri), label: item.title })) })
  } catch { if (active && generation === searchGeneration) { update(() => { options.value = [] }); dialogError.value = t('documents.datasetAttachments.error') } }
  finally { if (active && generation === searchGeneration) searching.value = false }
}
async function attach(): Promise<void> {
  if (!state.value || !selected.value || busy.value) return
  busy.value = true; dialogError.value = ''
  try {
    const result = await memoryService.attachDataset(props.documentId, selected.value, props.agentId, state.value.lock_version)
    if (!active) return
    state.value = result; adding.value = false; emit('changed')
  } catch { if (active) dialogError.value = t('documents.datasetAttachments.error') }
  finally { if (active) busy.value = false }
}
async function remove(uri: string): Promise<void> {
  if (!state.value || busy.value) return
  busy.value = true; error.value = ''
  try {
    const result = await memoryService.detachDataset(props.documentId, identity(uri), props.agentId, state.value.lock_version)
    if (!active) return
    state.value = result; emit('changed')
  } catch { if (active) error.value = t('documents.datasetAttachments.error') }
  finally { if (active) busy.value = false }
}
onMounted(load)
onBeforeUnmount(() => { active = false; searchGeneration++ })
</script>
