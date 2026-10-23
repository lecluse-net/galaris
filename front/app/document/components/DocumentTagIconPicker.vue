<template>
  <LibraryIconPicker v-model="open" :busy="busy" :save="save" :default-icon="defaultIcon" :document="document"
    :load-icons="documentService.listDocumentTagIcons" :upload-icon="documentService.uploadDocumentTagIcon" />
</template>
<script setup lang="ts">
import { LibraryIconPicker } from '@/core/util'
import { documentService } from '../services/documentService'
const open = defineModel<boolean>({ required: true })
defineProps<{ busy: boolean; save: (icon: string | null) => Promise<boolean>; defaultIcon?: string; document?: boolean }>()
</script>
