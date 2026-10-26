<template>
  <section class="folder-collection q-pa-md" :aria-busy="loading">
    <div class="row items-center q-gutter-sm q-mb-md">
      <LibraryIcon :icon="folder?.metadata.icon" size="32px" />
      <h2 class="text-h6 col q-ma-none">{{ folderId ? folder?.name || t('documents.collections.title') : t('documents.collections.title') }}</h2>
      <CopyResourceReference v-if="folderId" :uri="`document://folders/${folderId}/`" />
      <q-btn flat round icon="refresh" :aria-label="t('common.retry')" @click="load" />
    </div>
    <p v-if="folderId" class="text-caption">{{ t('documents.collections.hint') }}</p>
    <q-input v-model="query" outlined dense clearable debounce="300" :label="t('documents.collections.search')" class="q-mb-md" />
    <q-linear-progress v-if="loading" indeterminate />
    <q-banner v-if="error" role="alert">{{ t('documents.loadError') }} <q-btn outline color="primary" :label="t('common.retry')" @click="load" /></q-banner>
    <q-list v-else separator>
      <q-item v-for="entry in entries" :key="entry.uri" clickable @click="open(entry)">
        <q-item-section avatar><LibraryIcon v-if="entry.is_collection" :icon="entry.metadata.icon" size="36px" /><q-icon v-else name="description" size="32px" color="primary" /></q-item-section>
        <q-item-section><q-item-label>{{ entry.name }}</q-item-label></q-item-section>
        <q-item-section side><q-icon :name="selection ? 'add_circle_outline' : 'chevron_right'" /></q-item-section>
      </q-item>
    </q-list>
    <p v-if="!loading && !error && !entries.length" role="status" class="q-pa-md">{{ t('documents.empty') }}</p>
    <div class="row items-center justify-center q-gutter-sm q-mt-md">
      <q-select v-model="pageSize" :options="[10, 20, 50, 100, 500]" outlined dense :aria-label="t('documents.library.pageSize')" />
      <q-pagination v-model="page" :max="Math.max(1, Math.ceil(total / pageSize))" :max-pages="5" direction-links />
    </div>
    <ResourceDetailDialog v-if="target" :target="target" @close="target = null" />
  </section>
</template>
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AUTH_TOKEN_CHANGED_EVENT } from '@/core/api'
import { LibraryIcon, CopyResourceReference, ResourceDetailDialog, richLinkTarget, type ResourceDetailTarget } from '@/core/util'
import { documentService, type DocumentFolderEntry } from '../services/documentService'
const { folderId = null, agentId = null, selection = false } = defineProps<{ folderId?: string | null; agentId?: number | null; selection?: boolean }>()
const emit = defineEmits<{ select: [entry: DocumentFolderEntry] }>()
const { t } = useI18n()
const folder = ref<DocumentFolderEntry | null>(null), entries = ref<DocumentFolderEntry[]>([])
const query = ref(''), page = ref(1), pageSize = ref(50), total = ref(0), loading = ref(false), error = ref(false)
const target = shallowRef<ResourceDetailTarget | null>(null)
let request: AbortController | undefined
async function load(): Promise<void> {
  request?.abort(); const current = new AbortController(); request = current
  loading.value = true; error.value = false; entries.value = []; folder.value = null; total.value = 0
  try {
    const result = await documentService.folderCollection(folderId, agentId, { query: query.value || '', limit: pageSize.value, offset: (page.value - 1) * pageSize.value }, current.signal)
    if (current.signal.aborted) return
    folder.value = result.folder; entries.value = result.entries; total.value = result.total
  } catch { if (!current.signal.aborted) error.value = true }
  finally { if (!current.signal.aborted) loading.value = false }
}
function open(entry: DocumentFolderEntry): void {
  if (selection) emit('select', entry)
  else target.value = richLinkTarget(entry.uri, entry.name, agentId)
}
watch(() => [folderId, agentId, query.value, pageSize.value], () => {
  target.value = null
  if (page.value !== 1) page.value = 1
  else void load()
}, { immediate: true })
watch(page, () => { void load() })
onMounted(() => window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, load))
onBeforeUnmount(() => { request?.abort(); window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, load) })
</script>
<style scoped>
.folder-collection { min-width: 0; }
</style>
