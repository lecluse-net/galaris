<template>
  <ActionContextMenu :target="target" :actions="actions" />
</template>
<script setup lang="ts">
import { documentTypes, type DocumentKind } from '../documentTypes'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { ActionContextMenu, type ContextAction } from '@/core/util'
import type { DocumentLibraryEntry } from '../types'
import { documentRowShortcuts, type DocumentRowAction } from '@/app/document/libraryShortcuts'
const { entry, busy, target } = defineProps<{ entry: DocumentLibraryEntry; busy: boolean; target: string }>()
const emit = defineEmits<{ select: []; create: [type?: DocumentKind]; action: [value: DocumentRowAction] }>()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const actions = computed<ContextAction[]>(() => {
  const shortcuts = documentRowShortcuts(entry, busy, () => emit('select'), () => emit('create'), action => emit('action', action))
  const standard = [
    { key: 'F4', icon: 'visibility', label: t('common.open'), shortcut: 'F4' },
    { key: 'F2', icon: 'edit', label: t('documents.library.renameTag'), shortcut: 'F2' },
    { key: 'Delete', icon: 'delete', label: t('common.delete'), shortcut: 'Delete', negative: true },
  ].flatMap(action => {
    const run = shortcuts[action.key as keyof typeof shortcuts]
    return run ? [{ ...action, run }] : []
  })
  const creations = shortcuts.F3 && privilegeStore.hasAnyPrivilege([privileges.DOCUMENT_EDIT, privileges.DOCUMENT_ADMIN]) ? documentTypes.map(type => ({ key: 'new-' + type.code, icon: type.icon,
    label: t('documents.createTypedDocument', { type: t(type.label) }), run: () => emit('create', type.code) })) : []
  return [...standard, ...creations]
})
</script>
