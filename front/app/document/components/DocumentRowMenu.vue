<template>
  <ActionContextMenu :target="target" :actions="actions" />
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ActionContextMenu, type ContextAction } from '@/core/util'
import type { DocumentLibraryEntry } from '../types'
import { documentRowShortcuts, type DocumentRowAction } from '@/app/document/libraryShortcuts'
const { entry, busy, target } = defineProps<{ entry: DocumentLibraryEntry; busy: boolean; target: string }>()
const emit = defineEmits<{ select: []; create: []; action: [value: DocumentRowAction] }>()
const { t } = useI18n()
const actions = computed<ContextAction[]>(() => {
  const shortcuts = documentRowShortcuts(entry, busy, () => emit('select'), () => emit('create'), action => emit('action', action))
  return [
    { key: 'F4', icon: 'visibility', label: t('common.open'), shortcut: 'F4' },
    { key: 'F2', icon: 'edit', label: t('documents.library.renameTag'), shortcut: 'F2' },
    { key: 'F3', icon: 'note_add', label: t('documents.library.newSubdocumentAction'), shortcut: 'F3' },
    { key: 'Delete', icon: 'delete', label: t('common.delete'), shortcut: 'Delete', negative: true },
  ].flatMap(action => {
    const run = shortcuts[action.key as keyof typeof shortcuts]
    return run ? [{ ...action, run }] : []
  })
})
</script>
