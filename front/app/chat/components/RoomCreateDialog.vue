<template>
  <q-dialog
    :model-value="modelValue"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <q-card class="room-create-card">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6">{{ t('chat.newRoom') }}</div>
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
        <AgentSelect
          v-model="agentId"
          :options="agentOptions"
          scope="dialogue"
          :load-agents="false"
          emit-value
          map-options
          outlined
          autofocus
          :aria-label="t('chat.agent')"
        >
          <template #avatar="{ option, size }">
            <InternalAgentAvatar :agent-id="option.value" :name="option.label" :size="size" />
          </template>
        </AgentSelect>

        <q-input
          v-model="label"
          outlined
          maxlength="500"
          :label="t('chat.roomPreferences.name')"
        />

        <div v-if="modelValue && canEditTopic">
          <TopicSelect
            v-model="topicId"
            allow-create
            :disable="saving"
            outlined
            :label="t('chat.roomPreferences.topic')"
          />
          <div class="text-caption text-grey-7 q-mt-xs">
            {{ t('chat.roomPreferences.topicHint') }}
          </div>
        </div>

        <q-banner
          v-if="topicId === null"
          dense
          rounded
          class="dream-topic-hint text-caption"
        >
          <template #avatar>
            <q-icon name="auto_awesome" size="18px" />
          </template>
          {{ t('chat.roomPreferences.dreamTopicHint') }}
        </q-banner>

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
        <q-btn v-close-popup flat :label="t('chat.cancel')" />
        <q-btn
          color="primary"
          :label="t('chat.create')"
          :loading="saving"
          :disable="agentId === null || !label.trim()"
          @click="create"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { TopicSelect } from '@/app/topic'
import type { MessengerAgent } from '../types'
import { AgentSelect } from '@/app/agent'
import InternalAgentAvatar from './InternalAgentAvatar.vue'

const {
  modelValue,
  agents,
  saving = false,
  canEditTopic = false,
} = defineProps<{
  modelValue: boolean
  agents: MessengerAgent[]
  saving?: boolean
  canEditTopic?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  create: [
    agentId: number,
    label: string,
    topicId: string | null,
    showLastMessage: boolean,
  ]
}>()

const { t } = useI18n()
const agentId = ref<number | null>(null)
const label = ref('')
const topicId = ref<string | null>(null)
const showLastMessage = ref(true)
let suggestedLabel = ''

const agentOptions = computed(() =>
  agents.map(agent => ({ label: agent.display_name, value: agent.agent_id })),
)

watch(
  () => modelValue,
  open => {
    if (!open) return
    agentId.value = null
    label.value = ''
    topicId.value = null
    showLastMessage.value = true
    suggestedLabel = ''
  },
)

watch(agentId, selectedAgentId => {
  const nextSuggestion =
    agents.find(agent => agent.agent_id === selectedAgentId)?.display_name ?? ''
  if (!label.value.trim() || label.value === suggestedLabel) {
    label.value = nextSuggestion
  }
  suggestedLabel = nextSuggestion
})

function create(): void {
  const normalizedLabel = label.value.trim()
  if (agentId.value === null || !normalizedLabel) return
  emit(
    'create',
    agentId.value,
    normalizedLabel,
    canEditTopic ? topicId.value : null,
    showLastMessage.value,
  )
}
</script>

<style scoped>
.room-create-card {
  width: min(92vw, 520px);
}

.dream-topic-hint {
  color: var(--q-primary);
  background: color-mix(in srgb, var(--q-primary) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--q-primary) 24%, transparent);
}
</style>
