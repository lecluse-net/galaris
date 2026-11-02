<template>
  <span v-if="readonly || !canReadIcons" class="document-icon document-icon--readonly" role="img" :aria-label="t('documents.library.documentIcon', { name: title })">
    <DocumentTagIcon :icon="customIcon" :size="size" :default-icon="getDocumentType(type).icon" />
    <q-icon v-if="customIcon" :name="getDocumentType(type).icon" class="document-type-marker" :aria-label="t(getDocumentType(type).label)" />
  </span>
  <q-btn v-else flat :round="!plain" :square="plain" :ripple="!plain" :padding="plain ? 'none' : undefined" dense size="sm"
    class="document-icon" :class="{ 'document-icon--plain': plain }" :aria-label="t('documents.library.documentIcon', { name: title })"
    :disable="store.saving[documentId]" @click.stop="showPicker" @dblclick.stop @keydown.enter.stop @keydown.space.stop>
    <DocumentTagIcon :icon="customIcon" :size="size" :default-icon="getDocumentType(type).icon" />
    <q-icon v-if="customIcon" :name="getDocumentType(type).icon" class="document-type-marker" :aria-label="t(getDocumentType(type).label)" />
    <q-tooltip>{{ t(store.errors[documentId] ? 'documents.library.iconLoadError' : 'documents.library.iconHint') }}</q-tooltip>
    <DocumentTagIconPicker v-model="open" :busy="Boolean(store.saving[documentId])" :save="save" :default-icon="getDocumentType(type).icon" document />
  </q-btn>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import type { DocumentType } from '../types'
import { documentType as getDocumentType } from '../documentTypes'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { useDocumentIcons } from '@/app/document/stores/documentIcons'
import DocumentTagIcon from '@/app/document/components/DocumentTagIcon.vue'
import DocumentTagIconPicker from '@/app/document/components/DocumentTagIconPicker.vue'

const { documentId, title, size = '22px', readonly = false, plain = false, documentType: type = 'text' } = defineProps<{
  documentId: string; title: string; documentType?: DocumentType; size?: string; readonly?: boolean; plain?: boolean
}>()
const { t } = useI18n()
const $q = useQuasar()
const store = useDocumentIcons()
const privilegeStore = usePrivilegeStore()
const canReadIcons = computed(() => privilegeStore.hasAnyPrivilege([
  privileges.DOCUMENT_ACCESS, privileges.DOCUMENT_EDIT, privileges.DOCUMENT_ADMIN,
]))
const customIcon = computed(() => canReadIcons.value ? store.icons[documentId] : undefined)
const open = ref(false)
watch(() => [documentId, store.session, canReadIcons.value], () => {
  open.value = false
  if (canReadIcons.value) store.ensure(documentId)
}, { immediate: true })
function showPicker(): void { store.ensure(documentId); open.value = true }
async function save(icon: string | null): Promise<boolean> {
  const id = documentId
  try { return await store.save(id, icon) }
  catch { if (id === documentId) $q.notify({ type: 'negative', message: t('documents.library.iconSaveError') }); return false }
}
</script>
<style scoped>
.document-icon { position: relative; flex-shrink: 0; vertical-align: middle; color: var(--solaire-gray-accent); }
.document-type-marker { position: absolute; right: -2px; bottom: -2px; font-size: 12px; border-radius: 3px; background: var(--solaire-gray-light); }
:global(body.body--dark) .document-type-marker { background: var(--solaire-gray-dark); }
.document-icon--readonly { display: inline-flex; align-items: center; justify-content: center; }
.document-icon--plain :deep(.q-focus-helper) { display: none; }
.document-icon--plain:focus-visible { outline: 2px solid var(--solaire-blue-accent); outline-offset: 2px; }
</style>
