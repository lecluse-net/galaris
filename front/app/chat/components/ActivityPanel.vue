<template>
  <div class="activity-panel">
    <q-list dense separator>
      <q-item v-for="item in activity" :key="item.id" :class="{ 'activity-error': isProblem(item.status) }">
        <q-item-section avatar>
          <q-icon :name="isProblem(item.status) ? 'error' : item.status === 'RUNNING' ? 'hourglass_top' : 'hub'" :color="isProblem(item.status) ? 'negative' : undefined" />
        </q-item-section>
        <q-item-section>
          <q-item-label v-if="isProblem(item.status)" class="text-negative">{{ t('chat.executionProblem') }}</q-item-label>
          <q-item-label v-else-if="item.status === 'RUNNING'">{{ t('chat.thinking') }}</q-item-label>
          <q-item-label v-else>{{ formatTimestamp(item.created_at) }}</q-item-label>
          <q-item-label caption>{{ item.tools_used.join(', ') || t('chat.noTools') }}</q-item-label>
        </q-item-section>
      </q-item>
      <q-item v-if="!activity.length">
        <q-item-section class="text-grey">{{ t('chat.noActivity') }}</q-item-section>
      </q-item>
    </q-list>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { ConversationActivity } from '../types'

defineProps<{ activity: ConversationActivity[] }>()
const { t } = useI18n()
function isProblem(status: string): boolean { return ['FAILED', 'ERROR_RESOLVED', 'CANCELLED'].includes(status) }
function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
}
</script>

<style scoped>
.activity-panel { color: var(--chat-text, inherit); background: var(--chat-surface, transparent); overflow: auto; }
.activity-error { background: var(--chat-danger-soft, rgba(198, 52, 61, .08)); }
</style>
