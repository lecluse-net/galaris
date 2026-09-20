<template>
  <section class="interaction-choice" :aria-label="choice.title">
    <strong>{{ choice.title }}</strong>
    <SafeMessageContent v-if="choice.body" :content="choice.body" />
    <div class="interaction-options">
      <q-btn
        v-for="option in choice.options"
        :key="option.id"
        no-caps
        outline
        align="left"
        :label="option.label"
        :aria-pressed="choice.selected_option_id === option.id"
        :icon="choice.selected_option_id === option.id ? 'check_circle' : undefined"
        :loading="pendingOption === option.id"
        :disable="!canAnswer || pendingOption !== null"
        :class="{ 'interaction-option--selected': choice.selected_option_id === option.id }"
        @click="answer(option.id)"
      />
    </div>
    <small>#{{ choice.reference }}</small>
    <p v-if="status !== 'PENDING'" class="interaction-status" role="status">
      {{ t(`chatInteraction.${status.toLowerCase()}`) }}
    </p>
    <p v-else-if="choice.free_text && canAnswer" class="interaction-status">
      {{ t('chatInteraction.freeText') }}
    </p>
    <p v-if="error" class="interaction-error" role="alert">{{ error }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { chatService } from '../services/chatService'
import type { MessengerInteraction } from '../types'
import SafeMessageContent from './SafeMessageContent.vue'

const props = defineProps<{ roomId: string; interaction: MessengerInteraction; readonly?: boolean }>()
const { t } = useI18n()
const captured = ref<MessengerInteraction | null>(null)
const pendingOption = ref<string | null>(null)
const error = ref('')
const now = ref(Date.now())
const ranks = { PENDING: 0, EXPIRED: 1, PROCESSING: 2, RESOLVED: 3 }
// A delayed history refresh must not replace the successful click response with PENDING.
const choice = computed(() => captured.value && ranks[captured.value.status] > ranks[props.interaction.status]
  ? captured.value : props.interaction)
const status = computed(() => choice.value.status === 'PENDING' && Date.parse(choice.value.expires_at) <= now.value
  ? 'EXPIRED' : choice.value.status)
const canAnswer = computed(() => !props.readonly && props.interaction.can_answer && choice.value.can_answer && status.value === 'PENDING')
let generation = 0
watch([() => props.roomId, () => props.interaction.id], () => {
  generation += 1
  captured.value = null
  pendingOption.value = null
  error.value = ''
})
const timer = window.setInterval(() => { now.value = Date.now() }, 1000)
onUnmounted(() => { generation += 1; window.clearInterval(timer) })

async function answer(optionId: string): Promise<void> {
  if (!canAnswer.value || pendingOption.value !== null) return
  const requestGeneration = generation
  const { roomId, interaction } = props
  const current = () => generation === requestGeneration
  pendingOption.value = optionId
  error.value = ''
  try {
    const result = await chatService.answerInteraction(roomId, interaction.id, optionId)
    if (current()) captured.value = result
  } catch {
    if (!current()) return
    // The response can be lost after capture; re-read before offering another choice.
    try {
      const result = await chatService.interaction(roomId, interaction.id)
      if (current()) captured.value = result
    } catch { /* The same option remains safe to retry: the server owns idempotency. */ }
    if (current() && status.value === 'PENDING') error.value = t('chatInteraction.failed')
  } finally {
    if (current()) pendingOption.value = null
  }
}
</script>

<style scoped>
.interaction-choice { display: grid; gap: 12px; min-width: 0; }
.interaction-options { display: flex; flex-wrap: wrap; gap: 8px; }
.interaction-options :deep(.q-btn) { max-width: 100%; color: var(--solaire-blue-accent); }
.interaction-option--selected { color: var(--solaire-green-accent) !important; }
.interaction-status, .interaction-error { margin: 0; font-size: .875rem; }
.interaction-error { color: var(--solaire-red-accent); }
</style>
