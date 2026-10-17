<template>
  <ResourceSharingPanel :item-id="id" :lock-version="lockVersion" :editable="editable"
    :reader="service.sharing" :writer="save" @changed="emit('changed', $event)" />
</template>
<script setup lang="ts">
import { ResourceSharingPanel, type SharingUpdate } from '@/app/share'
import { datasetService as service } from '../services/datasetService'
import type { DatasetSharing } from '../types'
defineProps<{ id: string; lockVersion: number; editable: boolean }>()
const emit = defineEmits<{ changed: [state: DatasetSharing] }>()
async function save(id: string, data: SharingUpdate): Promise<DatasetSharing> {
  return await service.share(id, data, data.expected_lock_version)
}
</script>
