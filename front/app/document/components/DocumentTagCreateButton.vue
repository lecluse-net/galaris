<template>
  <q-btn :flat="!!parentId" :outline="!parentId" dense :round="!!parentId" :no-caps="!parentId"
    icon="create_new_folder" :label="parentId ? undefined : t('documents.library.newFolderName')" :size="parentId ? 'sm' : undefined" :disable="busy"
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
