<template>
  <ChatExecutionDetails
    :label="t('chat.executionDetail')" :icon="summaryIcon" :tools="tools" :recent-tools="activity.tools"
    :badge-label="t('chat.deep.mode')"
    :running="active" :error="failed" :expandable="hasDetails" @open="emit('inspect')"
  >
    <template #status>
      <span v-if="showStatus" class="text-caption" role="status">
        {{ t(submission.approvals.length ? 'chat.deep.approval' : stateKey) }}
      </span>
    </template>
    <template v-if="active && controllable && !submission.stop_requested && ['queued', 'running'].includes(submission.state)" #controls>
      <q-btn
        flat round dense size="sm" icon="stop" :aria-label="t('chat.deep.stop')"
        @click="emit('stop')"
      >
        <q-tooltip>{{ t('chat.deep.stop') }}</q-tooltip>
      </q-btn>
    </template>
    <q-btn v-for="approval in submission.approvals" :key="approval" outline dense no-caps color="primary"
      icon="policy" :label="t('chat.deep.approval')" :to="{ path: '/permissions', query: { request: approval } }" />
    <DeepActivityItem v-for="block in activity.roots" :key="block.id" :block="block" :blocks="activity.children" />
  </ChatExecutionDetails>
  <div v-if="showResponse && renderedBlocks.length" class="deep-response">
    <q-btn
      v-if="hiddenBlocks" outline dense no-caps color="primary" :label="t('chat.deep.previous')"
      @click="visibleBlocks += 8"
    />
    <SafeMessageContent
      v-for="(block, index) in renderedBlocks" :key="textBlocks.length - renderedBlocks.length + index"
      :content="block" :streaming="submission.state === 'running' && index === renderedBlocks.length - 1"
    />
  </div>
  <p v-if="failureText" class="deep-response deep-failure" role="status">{{ failureText }}</p>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ChatExecutionDetails from './ChatExecutionDetails.vue'
import SafeMessageContent from './SafeMessageContent.vue'
import DeepActivityItem from './DeepActivityItem.vue'
import { projectDeepActivity } from '../deepActivity'
import type { DeepEvent, DeepSubmission } from '../types'

const props = defineProps<{
  submission: DeepSubmission
  events: DeepEvent[]
  showResponse: boolean
  controllable: boolean
}>()
const emit = defineEmits<{ inspect: []; stop: [] }>()
const { t } = useI18n()
const stateKey = computed(() => props.submission.state === 'running' && props.submission.stop_requested
  ? 'chat.deep.stopping'
  : `chat.deep.${props.submission.state}`)
const inProgress = computed(() => ['queued', 'running', 'steering'].includes(props.submission.state))
const active = computed(() => props.showResponse && inProgress.value)
const showStatus = computed(() => props.submission.approvals.length || (inProgress.value ? active.value : props.submission.state !== 'completed'))
const failed = computed(() => ['failed', 'interrupted'].includes(props.submission.state))
const failureText = computed(() => {
  if (props.submission.state !== 'failed') return ''
  const failure = props.submission.failure
  if (failure?.code === 'http' && failure.http_status) {
    return t('chat.deep.failure.http', { status: failure.http_status })
  }
  return t(`chat.deep.failure.${failure?.code === 'http' ? 'runtime' : failure?.code ?? 'unrecorded'}`)
})
const summaryIcon = computed(() => failed.value ? 'error' : props.submission.approvals.length ? 'hourglass_top' : 'settings_suggest')
const activity = computed(() => projectDeepActivity(props.events))
const hasDetails = computed(() => props.submission.has_activity || props.submission.approvals.length > 0)
const tools = computed(() => [...new Set(activity.value.roots.map(block => block.name).filter(Boolean))])
const textBlocks = computed(() => activity.value.text)
const visibleBlocks = ref(8)
const renderedBlocks = computed(() => textBlocks.value.slice(-visibleBlocks.value))
const hiddenBlocks = computed(() => textBlocks.value.length > visibleBlocks.value)
</script>

<style scoped>
.deep-failure { margin: 0; color: var(--q-negative); }
.body--dark .deep-failure { color: var(--solaire-red-accent); }
</style>
