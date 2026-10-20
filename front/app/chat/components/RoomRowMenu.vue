<template>
  <ActionContextMenu target=".room-item" :actions="actions" />
  <RoomPreferencesDialog v-if="editable" v-model="preferences" :room="room" :saving="busy" :archiving="busy"
    :can-edit-topic="canEditTopic" @save="save" @archive="archive" />
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { apiErrorDetail } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { ActionContextMenu, useResourceCopy, type ContextAction } from '@/core/util'
import RoomPreferencesDialog from './RoomPreferencesDialog.vue'
import { chatService } from '../services/chatService'
import type { MessengerRoom } from '../types'
const { room, editable } = defineProps<{ room: MessengerRoom; editable: boolean }>()
const emit = defineEmits<{ select: []; changed: [room: MessengerRoom] }>()
const { t } = useI18n(), $q = useQuasar(), permissions = usePrivilegeStore()
const preferences = ref(false), busy = ref(false)
const { action: copyAction } = useResourceCopy()
const canEditTopic = computed(() => editable && permissions.hasPrivilege(privileges.TOPIC_EDIT))
let active = true
onBeforeUnmount(() => { active = false })
async function change(operation: () => Promise<MessengerRoom>): Promise<void> {
  if (!editable || busy.value) return
  busy.value = true
  try {
    const updated = await operation()
    if (active) { preferences.value = false; emit('changed', updated) }
  } catch (error) { if (active) $q.notify({ type: 'negative', message: apiErrorDetail(error) ?? t('chat.error') }) }
  finally { busy.value = false }
}
async function save(label: string, showLastMessage: boolean, topicId: string | null): Promise<void> {
  const snapshot = room
  await change(async () => {
    const updated = await chatService.updateRoomPreferences(snapshot.id, label, showLastMessage)
    if (!active || !canEditTopic.value || topicId === snapshot.topic_id) return updated
    try { return await chatService.updateRoomTopic(snapshot.id, topicId) }
    catch (error) { if (active) emit('changed', updated); throw error }
  })
}
function archive(archived: boolean): Promise<void> { return change(() => chatService.setArchived(room.id, archived)) }
const actions = computed<ContextAction[]>(() => [
  { key: 'open', icon: 'forum', label: t('common.open'), run: () => emit('select') },
  copyAction(`galaris://room/${room.id}`),
  ...(editable ? [
    { key: 'rename', icon: 'edit', label: t('chat.roomPreferences.name'), disabled: busy.value, run: () => { preferences.value = true } },
    { key: 'preferences', icon: 'settings', label: t('chat.roomPreferences.open'), disabled: busy.value, run: () => { preferences.value = true } },
    ...(canEditTopic.value ? [{ key: 'topic', icon: 'edit', label: t('chat.roomPreferences.topic'), disabled: busy.value, run: () => { preferences.value = true } }] : []),
    { key: 'archive', icon: room.archived ? 'unarchive' : 'archive', label: t(room.archived ? 'chat.roomPreferences.unarchive' : 'chat.roomPreferences.archive'), disabled: busy.value, run: () => archive(!room.archived) },
  ] : []),
])
</script>
