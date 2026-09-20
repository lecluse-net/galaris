<template>
  <q-badge
    class="llm-output-token-badge"
    color="blue-grey-6"
    tabindex="0"
    :title="tokenSummary"
    :aria-label="tokenSummary"
  >
    <q-icon name="title" size="xs" class="q-mr-xs" />
    {{ formattedOutputTokens }}
  </q-badge>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { LLMCall } from '../types'

type LlmCallTokenUsage = Pick<LLMCall, 'input_tokens' | 'cache_read_tokens' | 'output_tokens'>

const props = defineProps<{
  call: LlmCallTokenUsage
}>()

const { t, locale } = useI18n()

function formatTokenCount(value: number): string {
  return new Intl.NumberFormat(locale.value).format(value)
}

const formattedInputTokens = computed(() => formatTokenCount(props.call.input_tokens))
const formattedCacheReadTokens = computed(() => formatTokenCount(props.call.cache_read_tokens))
const formattedOutputTokens = computed(() => formatTokenCount(props.call.output_tokens))
const tokenSummary = computed(() => t('llmCalls.tokens.summary', {
  input: formattedInputTokens.value,
  inputCache: formattedCacheReadTokens.value,
  output: formattedOutputTokens.value,
}))
</script>
