<template>
  <span v-if="readonly" class="document-icon document-icon--readonly" role="img" :aria-label="t('documents.library.documentIcon', { name: title })">
    <DocumentTagIcon :icon="store.icons[documentId]" :size="size" default-icon="description" />
  </span>
  <q-btn v-else flat round dense size="sm" class="document-icon" :aria-label="t('documents.library.documentIcon', { name: title })"
    :disable="store.saving[documentId]" @click.stop="showPicker" @dblclick.stop @keydown.enter.stop @keydown.space.stop>
    <DocumentTagIcon :icon="store.icons[documentId]" :size="size" default-icon="description" />
    <q-tooltip>{{ t(store.errors[documentId] ? 'documents.library.iconLoadError' : 'documents.library.iconHint') }}</q-tooltip>
    <DocumentTagIconPicker v-model="open" :busy="Boolean(store.saving[documentId])" :save="save" default-icon="description" document />
  </q-btn>
</template>
<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { useDocumentIcons } from '../stores/documentIcons'
import DocumentTagIcon from './DocumentTagIcon.vue'
import DocumentTagIconPicker from './DocumentTagIconPicker.vue'

const { documentId, title, size = '22px', readonly = false } = defineProps<{ documentId: string; title: string; size?: string; readonly?: boolean }>()
const { t } = useI18n()
const $q = useQuasar()
const store = useDocumentIcons()
const open = ref(false)
watch(() => [documentId, store.session], () => { open.value = false; store.ensure(documentId) }, { immediate: true })
function showPicker(): void { store.ensure(documentId); open.value = true }
async function save(icon: string | null): Promise<boolean> {
  const id = documentId
  try { return await store.save(id, icon) }
  catch { if (id === documentId) $q.notify({ type: 'negative', message: t('documents.library.iconSaveError') }); return false }
}
</script>
<style scoped>
.document-icon { flex-shrink: 0; vertical-align: middle; color: var(--solaire-gray-accent); }
.document-icon--readonly { display: inline-flex; align-items: center; justify-content: center; }
</style>
