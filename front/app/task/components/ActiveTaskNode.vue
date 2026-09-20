<template>
  <div class="active-task-node">
    <div
      class="active-task-row"
      :style="rowStyle"
      role="button"
      tabindex="0"
      @click="$emit('select', task.id)"
      @keydown.enter.prevent="$emit('select', task.id)"
      @keydown.space.prevent="$emit('select', task.id)"
    >
      <div class="active-task-icon">
        <q-spinner v-if="isAction" :color="statusColor" size="18px" />
        <q-icon v-else :name="statusIcon" :color="statusColor" size="18px" />
      </div>
      <div class="active-task-time">{{ timestamp }}</div>
      <div class="active-task-agent">
        <q-avatar size="24px" color="grey-3" text-color="grey-7" class="active-task-agent-avatar">
          <img v-if="agentAvatarUrl" :src="agentAvatarUrl" alt="" />
          <q-icon v-else name="person" size="16px" />
        </q-avatar>
        <span class="active-task-agent-name">{{ agentName }}</span>
      </div>
      <div class="active-task-main">
        <div v-if="task.topic_id" class="active-task-topic-line">
          <TopicBadge
            :topic-id="task.topic_id"
            :title="topicTitles?.[task.topic_id]"
            subject-kind="task"
            :subject-id="task.id"
          />
        </div>
        <div class="active-task-label">
          <q-icon v-if="(depth || 0) > 0" name="subdirectory_arrow_right" size="14px" color="grey-6" class="q-mr-xs" />
          {{ task.label }}
        </div>
        <div v-if="descriptionText" class="active-task-description">{{ descriptionText }}</div>
      </div>
      <div class="active-task-status">
        <StatusBadge :tone="statusTone" :label="statusLabel" class="active-task-badge" />
        <StatusBadge
          v-if="pauseBadge(task)"
          :tone="pauseBadge(task)!.tone"
          :label="$t(pauseBadge(task)!.labelKey)"
          :icon="pauseBadge(task)!.icon"
          class="active-task-badge"
        />
      </div>
    </div>

    <!-- Recursively nested subtasks -->
    <ActiveTaskNode
      v-for="child in childNodes"
      :key="child.id"
      :task="child"
      :avatar-urls="avatarUrls"
      :topic-titles="topicTitles"
      :children-map="childrenMap"
      :depth="(depth || 0) + 1"
      @select="$emit('select', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAgentStore } from '../../agent/stores/agentStore'
import type { Task } from '../types'
import TopicBadge from '@/app/topic/components/TopicBadge.vue'
import { StatusBadge, richTextExcerpt } from '@/core/util'
import {
  getTaskOperationalColor,
  getTaskOperationalIcon,
  getTaskStatusTone,
  pauseBadge,
  shouldAnimateTaskStatus
} from '../services/taskStatusService'

defineOptions({ name: 'ActiveTaskNode' })

const props = defineProps<{
  task: Task
  avatarUrls?: Record<number, string>
  topicTitles?: Record<string, string>
  childrenMap?: Map<string, Task[]>
  depth?: number
}>()
defineEmits<{ select: [taskId: string] }>()

// Direct children from the panel map, indented by depth.
const childNodes = computed<Task[]>(() => props.childrenMap?.get(props.task.id) ?? [])
const rowStyle = computed(() => (props.depth ? { paddingLeft: `${props.depth * 22}px` } : undefined))
const { t, locale } = useI18n()
const agentStore = useAgentStore()

function normalizeText(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

function truncate(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value
  return `${value.slice(0, maxLength - 3).trim()}...`
}

function formatDateTime(iso: string | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString(locale.value, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

function formatEpochSeconds(value: unknown): string {
  const seconds = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(seconds) || seconds <= 0) return ''
  return formatDateTime(new Date(seconds * 1000).toISOString())
}

const statusIcon    = computed(() => getTaskOperationalIcon(props.task))
const statusColor   = computed(() => getTaskOperationalColor(props.task))
const statusTone    = computed(() => getTaskStatusTone(props.task.status))
const statusLabel   = computed(() => t(`task.status.${props.task.status}`))
const isAction      = computed(() => shouldAnimateTaskStatus(props.task))
const timestamp     = computed(() => {
  const messageTime = formatEpochSeconds(props.task.data?.time)
  return messageTime || formatDateTime(props.task.created_at ?? props.task.updated_at)
})
const agent = computed(() => {
  if (props.task.agent_id == null) return null
  return agentStore.agents.find(e => e.id === props.task.agent_id) ?? null
})
const agentName = computed(() => {
  if (props.task.agent_id == null) return t('task.list.noAgent')
  if (!agent.value) return t('task.list.agentId', { id: props.task.agent_id })
  return `${agent.value.first_name} ${agent.value.last_name}`.trim()
})
const agentAvatarUrl = computed(() => {
  if (props.task.agent_id == null || !agent.value?.has_avatar) return undefined
  return props.avatarUrls?.[props.task.agent_id]
})
const descriptionText = computed(() => {
  const detail = richTextExcerpt(props.task.objective || '')
  return truncate(normalizeText(detail), 220)
})
</script>

<style scoped>
.active-task-node {
  margin-left: 0;
}

.active-task-row {
  display: grid;
  grid-template-columns: 30px 168px minmax(140px, 0.55fr) minmax(260px, 1.45fr) 132px;
  align-items: center;
  gap: 12px;
  min-height: 40px;
  padding: 3px 12px 3px 0;
  border-radius: 4px;
  cursor: pointer;
}

.active-task-row:hover {
  background-color: rgba(0, 0, 0, 0.04);
}

.active-task-row:focus-visible {
  outline: 2px solid var(--q-primary);
  outline-offset: 1px;
}

.active-task-icon {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.active-task-time,
.active-task-agent,
.active-task-label,
.active-task-description,
.active-task-status {
  min-width: 0;
}

.active-task-status {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  flex-wrap: wrap;
}

.active-task-time {
  color: #667085;
  font-size: 12px;
  white-space: nowrap;
}

body.body--dark .active-task-time,
body.body--dark .active-task-description {
  color: #98a2b8;
}

body.body--dark .active-task-agent {
  color: #cdd5e0;
}

body.body--dark .active-task-label {
  color: #e3e8f0;
}

.active-task-agent {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #344054;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  user-select: none;
}

.active-task-agent-avatar {
  flex: 0 0 24px;
}

.active-task-agent-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.active-task-main {
  min-width: 0;
}

.active-task-topic-line {
  display: flex;
  min-width: 0;
  margin-bottom: 2px;
}

.active-task-label {
  flex: 0 1 auto;
  color: #101828;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  user-select: none;
}

.active-task-description {
  margin-top: 2px;
  color: #667085;
  font-size: 12px;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  user-select: none;
}

.active-task-badge {
  flex-shrink: 0;
  justify-self: end;
}

@media (max-width: 1023px) {
  .active-task-node {
    margin-bottom: 8px;
  }

  .active-task-row {
    grid-template-columns: 30px 1fr auto;
    gap: 8px;
    align-items: start;
    min-height: 0;
    padding: 10px;
    border: 1px solid #e0e4ea;
    border-radius: 8px;
    background: #fff;
  }

  .active-task-row:hover,
  .active-task-row:focus-visible {
    border-color: var(--q-primary);
    background: rgb(25 118 210 / 4%);
  }

  body.body--dark .active-task-row {
    border-color: #3a3f47;
    background: #1f2329;
  }

  .active-task-time,
  .active-task-agent,
  .active-task-main {
    grid-column: 2;
  }

  .active-task-time {
    grid-row: 1;
  }

  .active-task-agent {
    grid-row: 2;
  }

  .active-task-main {
    grid-row: 3;
  }

  .active-task-status {
    grid-column: 3;
    grid-row: 1 / span 2;
    max-width: 120px;
  }

  .active-task-label,
  .active-task-description {
    white-space: normal;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }
}

@media (max-width: 599px) {
  .active-task-row {
    grid-template-columns: 24px minmax(0, 1fr);
  }

  .active-task-icon {
    width: 24px;
    height: 24px;
  }

  .active-task-time,
  .active-task-agent,
  .active-task-main,
  .active-task-status {
    grid-column: 2;
  }

  .active-task-time {
    grid-row: 1;
  }

  .active-task-agent {
    grid-row: 2;
  }

  .active-task-main {
    grid-row: 3;
  }

  .active-task-status {
    grid-row: 4;
    justify-content: flex-start;
    max-width: none;
  }
}
</style>
