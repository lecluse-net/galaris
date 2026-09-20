<template>
  <q-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)">
    <q-card class="room-preferences-card">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6">{{ t('chat.roomPreferences.title') }}</div>
        <q-space />
        <q-btn
          v-close-popup
          flat
          round
          dense
          icon="close"
          :aria-label="t('common.close')"
        />
      </q-card-section>

      <q-card-section class="q-gutter-md">
        <q-input
          v-model="label"
          outlined
          autofocus
          maxlength="500"
          :label="t('chat.roomPreferences.name')"
        />
        <div v-if="modelValue && canEditTopic">
          <TopicSelect
            :key="room?.id"
            v-model="topicId"
            allow-create
            :disable="saving || archiving"
            outlined
            :label="t('chat.roomPreferences.topic')"
          />
          <div class="text-caption text-grey-7 q-mt-xs">
            {{ t('chat.roomPreferences.topicHint') }}
          </div>
        </div>
        <div>
          <q-toggle
            v-model="showLastMessage"
            :label="t('chat.roomPreferences.showLastMessage')"
          />
          <div class="text-caption text-grey-7 q-ml-md">
            {{ t('chat.roomPreferences.privacyHint') }}
          </div>
        </div>
      </q-card-section>

      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn
          flat
          :color="room?.archived ? 'primary' : 'warning'"
          :icon="room?.archived ? 'unarchive' : 'archive'"
          :label="t(room?.archived ? 'chat.roomPreferences.unarchive' : 'chat.roomPreferences.archive')"
          :loading="archiving"
          :disable="saving"
          @click="toggleArchive"
        />
        <q-space />
        <q-btn v-close-popup flat :label="t('chat.cancel')" />
        <q-btn
          color="primary"
          :label="t('chat.roomPreferences.save')"
          :loading="saving"
          :disable="archiving || !label.trim()"
          @click="save"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { TopicSelect } from '@/app/topic'
import type { MessengerRoom } from '../types'

const { modelValue, room, saving = false, archiving = false, canEditTopic = false } = defineProps<{
  modelValue: boolean
  room: MessengerRoom | null
  saving?: boolean
  archiving?: boolean
  canEditTopic?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  save: [label: string, showLastMessage: boolean, topicId: string | null]
  archive: [archived: boolean]
}>()

const { t } = useI18n()
const label = ref('')
const showLastMessage = ref(true)
const topicId = ref<string | null>(null)

watch(
  () => [modelValue, room] as const,
  ([open, selectedRoom]) => {
    if (!open || !selectedRoom) return
    label.value = selectedRoom.label
    showLastMessage.value = selectedRoom.show_last_message
    topicId.value = selectedRoom.topic_id
  },
  { immediate: true },
)

function save(): void {
  const normalizedLabel = label.value.trim()
  if (!normalizedLabel) return
  emit('save', normalizedLabel, showLastMessage.value, topicId.value)
}

function toggleArchive(): void {
  if (!room) return
  emit('archive', !room.archived)
}
</script>

<style scoped>
.room-preferences-card {
  width: min(92vw, 520px);
}
</style>
