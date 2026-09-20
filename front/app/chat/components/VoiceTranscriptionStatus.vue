<template>
  <section class="execution-trace voice-transcription-status" role="status" aria-live="polite">
    <div class="trace-summary">
      <q-icon name="graphic_eq" class="summary-icon" />
      <span class="summary-label">{{ t('chat.transcriptionInProgress') }}</span>
      <q-spinner-dots color="primary" size="22px" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<style scoped>
.execution-trace { margin: 2px -9px 8px; overflow: hidden; color: var(--chat-text-secondary, #536071); background: var(--chat-surface-soft, #f5f7fa); border: 1px solid var(--chat-border, rgba(53, 69, 94, .1)); border-radius: 10px; }
.execution-trace:first-child { margin-top: -6px; }
.trace-summary { display: flex; width: 100%; min-height: 34px; align-items: center; flex-wrap: wrap; gap: 5px 7px; padding: 6px 9px; color: inherit; }
.summary-icon { font-size: 18px; }
.summary-label { font-size: .75rem; font-weight: 650; }
</style>
