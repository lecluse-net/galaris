<template>
  <q-btn flat dense round :icon="parentId ? 'create_new_folder' : 'add'" :size="parentId ? 'sm' : undefined" :disable="busy"
    :aria-label="parentId ? t('documents.library.newSubtag', { name: parentName }) : t('documents.library.newTag')" @click.stop="create">
    <q-tooltip>{{ parentId ? t('documents.library.newSubtag', { name: parentName }) : t('documents.library.newTag') }}</q-tooltip>
  </q-btn>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const props = defineProps<{
  parentId: string | null
  parentName?: string
  busy: boolean
  save: (name: string, parentId: string | null) => Promise<boolean>
}>()
const { t } = useI18n()
async function create(): Promise<void> {
  if (!props.busy) await props.save(t('documents.library.newFolderName'), props.parentId)
}
</script>
