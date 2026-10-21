<template>
  <LibraryIconPicker v-model="open" :busy="busy" :save="save" :default-icon="defaultIcon" :document="document"
    :load-icons="memoryService.listDocumentTagIcons" :upload-icon="memoryService.uploadDocumentTagIcon" />
</template>
<script setup lang="ts">
import { LibraryIconPicker } from '@/core/util'
import { memoryService } from '../services/memoryService'
const open = defineModel<boolean>({ required: true })
defineProps<{ busy: boolean; save: (icon: string | null) => Promise<boolean>; defaultIcon?: string; document?: boolean }>()
</script>
