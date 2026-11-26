<template>
  <section class="interaction-choice" :class="{ 'interaction-choice--authorization': choice.is_authorization }" :aria-label="choice.title">
    <header v-if="choice.is_authorization" class="authorization-header">
      <q-icon name="verified_user" size="22px" class="authorization-icon" aria-hidden="true" />
      <strong>{{ choice.title }}</strong>
      <small>#{{ choice.reference }}</small>
    </header>
    <strong v-else>{{ choice.title }}</strong>
    <RichText v-if="choice.body_html" :content="choice.body_html" :open-document-in-dialog="choice.is_authorization" />
    <SafeMessageContent v-else-if="choice.body" :content="choice.body" />
    <div class="interaction-options">
      <q-btn color="primary"
        v-for="option in visibleOptions"
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
    <small v-if="!choice.is_authorization">#{{ choice.reference }}</small>
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
import { RichText } from '@/core/util'
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
const status = computed(() => choice.value.status === 'PENDING' && Date.parse(choice.value.expires_at ?? '') <= now.value
  ? 'EXPIRED' : choice.value.status)
const visibleOptions = computed(() => {
  const current = choice.value
  return current.is_authorization && current.selected_option_id && (status.value === 'PROCESSING' || status.value === 'RESOLVED')
    ? current.options.filter(option => option.id === current.selected_option_id)
    : current.options
})
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
.interaction-choice :deep(.rich-content) { background-color: var(--chat-surface-raised, var(--rich-background)); }
.interaction-choice--authorization {
  --authorization-surface: var(--solaire-blue-light);
  --authorization-label-surface: var(--solaire-gray-light);
}
.body--dark .interaction-choice--authorization {
  --authorization-surface: var(--solaire-blue-dark);
  --authorization-label-surface: var(--solaire-gray-dark);
}
.authorization-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--authorization-surface);
  overflow-wrap: anywhere;
}
.authorization-icon { color: var(--solaire-blue-accent); }
.authorization-header small { margin-inline-start: auto; }
.interaction-choice--authorization :deep(.rich-content) { font-size: inherit; }
.interaction-choice--authorization :deep(.rich-content > h3:first-child) { margin: 0 0 8px; font-weight: 600; }
.interaction-choice--authorization :deep(.rich-content > table.galaris-table-gray.galaris-table-minimal) {
  border: 1px solid var(--chat-border, var(--rich-border));
  border-collapse: separate;
  border-spacing: 0;
  border-radius: 6px;
  overflow: hidden;
}
.interaction-choice--authorization :deep(.rich-content > table.galaris-table-gray.galaris-table-minimal > tbody > tr > :is(th, td)) {
  padding: 6px 10px;
  border: 0;
  background: transparent;
  color: var(--rich-foreground);
  vertical-align: top;
}
.interaction-choice--authorization :deep(.rich-content > table.galaris-table-gray.galaris-table-minimal > tbody > tr + tr > :is(th, td)) {
  border-block-start: 1px solid var(--chat-border, var(--rich-border));
}
.interaction-choice--authorization :deep(.rich-content > table.galaris-table-gray.galaris-table-minimal > tbody > tr > th) {
  width: 42%;
  text-align: start;
  background: var(--authorization-label-surface);
}
.interaction-choice--authorization :deep(.rich-content > blockquote:last-child) {
  margin: 12px 0 0;
  padding: 8px 10px;
  border-inline-start: 3px solid var(--solaire-blue-accent);
  border-radius: 4px;
  background: var(--authorization-surface);
  font-size: .875rem;
}
.interaction-options { display: flex; flex-wrap: wrap; gap: 8px; }
.interaction-options :deep(.q-btn) { max-width: 100%; color: var(--solaire-blue-accent); }
.interaction-option--selected { color: var(--solaire-green-accent) !important; }
.interaction-status, .interaction-error { margin: 0; font-size: .875rem; }
.interaction-error { color: var(--solaire-red-accent); }
</style>
