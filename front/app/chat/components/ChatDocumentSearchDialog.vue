<template>
  <q-dialog v-model="open">
    <q-card class="chat-document-search">
      <q-toolbar class="galaris-dialog-title">
        <q-toolbar-title>{{ t('chat.searchDocuments') }}</q-toolbar-title>
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-toolbar>
      <q-card-section>
        <q-input v-model="query" outlined autofocus clearable :label="t('chat.searchDocuments')">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </q-card-section>
      <div class="chat-document-results" :aria-busy="loading">
        <div v-if="loading" class="q-pa-md" role="status"><q-spinner color="primary" /></div>
        <div v-else-if="error" class="q-pa-md" role="alert">
          {{ t('chat.documentSearchError') }}
          <q-btn flat :label="t('chat.retryDocuments')" @click="search" />
        </div>
        <div v-else-if="!items.length" class="q-pa-md" role="status">{{ t('chat.noDocumentResults') }}</div>
        <q-list v-else separator>
          <q-item v-for="item in items" :key="item.id" clickable :aria-label="t('chat.openDocument', { label: item.title })" @click="select(item)">
            <q-item-section avatar><DocumentIcon :document-id="item.id" :title="item.title" /></q-item-section>
            <q-item-section><q-item-label>{{ item.title }}</q-item-label><q-item-label caption>{{ item.id }}</q-item-label></q-item-section>
          </q-item>
        </q-list>
      </div>
      <q-card-actions align="right">
        <q-select v-model="pageSize" dense outlined :options="[10, 20, 50, 100, 500]" :label="t('chat.documentsPerPage')" />
        <q-pagination v-model="page" :max="Math.max(1, Math.ceil(total / pageSize))" :max-pages="5" :disable="loading" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { WorkingDocumentIcon as DocumentIcon } from '@/core/util'
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { searchWorkingDocuments, type WorkingDocumentReference } from '@/core/util'

const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{ select: [document: WorkingDocumentReference] }>()
const { t } = useI18n()
const query = ref<string | null>('')
const items = ref<WorkingDocumentReference[]>([])
const page = ref(1), pageSize = ref(50), total = ref(0)
const loading = ref(false), error = ref(false)
let generation = 0
let timer: ReturnType<typeof setTimeout> | undefined

async function search(): Promise<void> {
  const current = ++generation
  loading.value = true
  error.value = false
  try {
    const result = await searchWorkingDocuments(query.value?.trim() ?? '', pageSize.value, (page.value - 1) * pageSize.value)
    if (current !== generation || !open.value) return
    items.value = result.items
    total.value = result.total
  } catch {
    if (current === generation) error.value = true
  } finally {
    if (current === generation) loading.value = false
  }
}
function schedule(): void {
  generation += 1
  clearTimeout(timer)
  items.value = []
  loading.value = open.value
  if (open.value) timer = setTimeout(() => { void search() }, 200)
}
function select(document: WorkingDocumentReference): void {
  emit('select', document)
  open.value = false
}
watch([query, pageSize], () => { page.value = 1; schedule() })
watch(page, schedule)
watch(open, () => { page.value = 1; schedule() }, { immediate: true })
onBeforeUnmount(() => { generation += 1; clearTimeout(timer) })
</script>

<style scoped>
.chat-document-search { display: flex; flex-direction: column; width: min(640px, 94vw); max-width: 94vw; max-height: 85dvh; }
.chat-document-results { flex: 1; min-height: 100px; overflow: auto; }
</style>
