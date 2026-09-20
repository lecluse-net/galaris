<template>
  <q-card class="recent-tasks-card">
    <q-card-section class="recent-tasks-header">
      <div class="row items-center justify-between">
        <div class="row items-center recent-tasks-title">
          <q-icon name="history" size="sm" class="q-mr-sm" />
          <span class="text-subtitle1">
            {{ $t('executionMonitoring.history', { count: store.recentTotal }) }}
          </span>
        </div>
        <div class="row items-center recent-tasks-filters">
          <q-input
            v-model="searchText"
            :label="$t('task.search')"
            clearable
            debounce="300"
            dense
            outlined
            class="recent-task-search"
          >
            <template #prepend>
              <q-icon name="search" />
            </template>
          </q-input>
          <AgentSelect
            v-model="selectedAgentId"
            :options="agentOptions"
            :label="$t('task.agentFilter')"
            clearable
            dense
            outlined
            class="recent-task-agent"
          />
          <TopicSelect
            v-model="selectedTopicId"
            :allow-create="false"
            :label="$t('topic.filter')"
            dense
            outlined
            class="recent-task-topic"
          />
          <ExecutionDateFilters
            v-model:date-from="dateFrom"
            v-model:date-to="dateTo"
            @change="dateRangeChanged"
          />
          <div class="recent-task-actions">
            <slot name="actions" />
          </div>
        </div>
      </div>
      <q-separator class="q-my-sm" />
    </q-card-section>

    <q-card-section class="recent-tasks-content q-pt-none">
      <div v-if="store.recentLoading && store.recentTasks.length === 0" class="text-center q-pa-md">
        <q-spinner color="primary" size="2em" />
      </div>

      <div v-else-if="store.recentTasks.length === 0" class="text-grey text-caption q-pa-xs">
        {{ $t('task.noTask') }}
      </div>

      <div v-else>
        <div class="active-tasks-header-row">
          <span>{{ $t('task.list.timestamp') }}</span>
          <span>{{ $t('task.list.agent') }}</span>
          <span>{{ $t('task.list.label') }}</span>
          <span>{{ $t('task.list.status') }}</span>
        </div>
        <ActiveTaskNode
          v-for="task in rootTasks"
          :key="task.id"
          :task="task"
          :avatar-urls="avatarUrls"
          :topic-titles="topicTitles"
          :children-map="childrenByParent"
          :depth="0"
          @select="$emit('select', $event)"
        />
      </div>
    </q-card-section>

    <q-card-actions
      v-if="store.recentTasks.length > 0"
      class="recent-tasks-pagination"
    >
      <div class="recent-tasks-page-size-control">
        <span class="text-caption text-grey-7">{{ $t('task.rowsPerPage') }}</span>
        <q-select
          v-model="selectedPageSize"
          :options="pageSizeOptions"
          dense
          borderless
          emit-value
          map-options
          options-dense
          class="recent-tasks-page-size"
        />
      </div>

      <div class="recent-tasks-pagination-right">
        <span class="recent-tasks-page-summary text-caption text-grey-7">
          {{ $t('task.pageNumberOf', { page: store.recentPage + 1, pages: store.recentPageCount }) }}
        </span>
        <q-btn-group flat class="recent-tasks-page-buttons">
          <q-btn
            flat
            dense
            icon="chevron_left"
            :disable="store.recentPage === 0 || store.recentLoading"
            @click="store.fetchRecentTasks(store.recentPage - 1)"
          />
          <q-btn
            flat
            dense
            icon="chevron_right"
            :disable="!store.recentHasMore || store.recentLoading"
            @click="store.fetchRecentTasks(store.recentPage + 1)"
          />
        </q-btn-group>
      </div>
    </q-card-actions>
  </q-card>
</template>

<script setup lang="ts">
import { onMounted, computed, reactive, watch } from 'vue'
import { useTaskStore } from '../stores/taskStore'
import { useAgentStore } from '../../agent/stores/agentStore'
import { agentService } from '../../agent/services/agentService'
import { AgentSelect } from '@/app/agent'
import { ExecutionDateFilters } from '@/core/util'
import ActiveTaskNode from './ActiveTaskNode.vue'
import type { Task } from '../types'
import { useTopicRefs } from '@/app/topic/composables/useTopicRefs'
import TopicSelect from '@/app/topic/components/TopicSelect.vue'

defineEmits<{ select: [taskId: string] }>()

const store = useTaskStore()
const agentStore = useAgentStore()
const avatarUrls = reactive<Record<number, string>>({})
const { titles: topicTitles, resolveTopicRefs } = useTopicRefs()

watch(
  () => store.recentTasks.map(task => task.topic_id),
  ids => { void resolveTopicRefs(ids) },
  { immediate: true },
)

function displayedAt(task: Task): number {
  const messageSeconds = Number(task.data?.time)
  if (Number.isFinite(messageSeconds) && messageSeconds > 0) {
    return messageSeconds * 1000
  }
  const timestamp = Date.parse(task.created_at ?? '')
  return Number.isFinite(timestamp) ? timestamp : 0
}

function compareByDisplayedDate(left: Task, right: Task, direction: 1 | -1): number {
  const dateOrder = (displayedAt(left) - displayedAt(right)) * direction
  if (dateOrder !== 0) return dateOrder
  return left.id.localeCompare(right.id) * direction
}

// Build the best-effort tree from the loaded page, grouping children by parent and
// rendering as roots only tasks without a loaded parent. This keeps orphaned
// children visible when their parent is outside the current page.
const childrenByParent = computed(() => {
  const map = new Map<string, Task[]>()
  for (const t of store.recentTasks) {
    if (t.parent_id) {
      const arr = map.get(t.parent_id)
      if (arr) arr.push(t)
      else map.set(t.parent_id, [t])
    }
  }
  // Subtasks are read chronologically, from the oldest to the newest.
  for (const children of map.values()) {
    children.sort((left, right) => compareByDisplayedDate(left, right, 1))
  }
  return map
})
const rootTasks = computed(() => {
  return buildRootTasks(store.recentTasks)
})


function buildRootTasks(tasks: Task[]): Task[] {
  const ids = new Set(tasks.map(task => task.id))
  return tasks
    .filter(task => !task.parent_id || !ids.has(task.parent_id))
    .sort((left, right) => compareByDisplayedDate(left, right, -1))
}

const agentOptions = computed(() =>
  agentStore.agents.map(e => ({
    value: e.id,
    label: `${e.first_name} ${e.last_name}`.trim()
  }))
)

const pageSizeOptions = computed(() =>
  store.recentPageSizeOptions.map(size => ({
    label: String(size),
    value: size
  }))
)

const searchText = computed<string>({
  get: () => store.recentSearchQuery,
  set: (val) => store.setRecentSearchQuery(val || '')
})

const selectedPageSize = computed<number>({
  get: () => store.recentPageSize,
  set: (val) => store.setRecentPageSize(Number(val))
})

const selectedAgentId = computed<number | null>({
  get: () => store.selectedAgentFilter,
  set: (val) => {
    store.selectedAgentFilter = val
    store.fetchRecentTasks(0)
  }
})

const selectedTopicId = computed<string | null>({
  get: () => store.recentTopicFilter,
  set: value => store.setRecentTopicFilter(value),
})

const dateFrom = computed<string | null>({
  get: () => store.recentDateFrom,
  set: value => { store.recentDateFrom = value },
})

const dateTo = computed<string | null>({
  get: () => store.recentDateTo,
  set: value => { store.recentDateTo = value },
})

function dateRangeChanged(): void {
  void store.fetchRecentTasks(0)
}

async function loadAvatars(): Promise<void> {
  await Promise.all(agentStore.agents.map(async agent => {
    if (!agent.has_avatar || avatarUrls[agent.id]) return
    try {
      avatarUrls[agent.id] = await agentService.getAvatarBlobUrl(agent.id)
    } catch (error) {
      console.error(`Failed to load avatar for agent ${agent.id}:`, error)
    }
  }))
}

onMounted(async () => {
  await agentStore.fetchAgents()
  await loadAvatars()
  store.fetchRecentTasks(0)
})
</script>

<style scoped>
.recent-tasks-card {
  width: 100%;
}

.recent-tasks-header {
  padding-bottom: 0;
}

.recent-tasks-header > .row {
  gap: 12px;
}

.recent-tasks-filters {
  display: flex;
  flex: 1 1 auto;
  flex-wrap: nowrap;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

.recent-task-search {
  flex: 0 1 220px;
  width: 220px;
  min-width: 140px;
  max-width: 220px;
}

.recent-task-agent {
  flex: 0 1 180px;
  width: 180px;
  min-width: 130px;
  max-width: 180px;
}

.recent-task-topic {
  flex: 0 1 220px;
  width: 220px;
  min-width: 150px;
  max-width: 220px;
}

.recent-task-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  margin-left: auto;
}

@media (max-width: 1023px) {
  .recent-tasks-header > .row {
    flex-wrap: wrap;
  }

  .recent-tasks-title,
  .recent-tasks-filters {
    width: 100%;
  }

  .recent-tasks-filters {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .recent-task-search,
  .recent-task-agent,
  .recent-task-topic {
    width: 100%;
    min-width: 0;
    max-width: none;
  }

  .recent-task-search,
  .recent-tasks-filters :deep(.execution-date-filters),
  .recent-task-actions {
    grid-column: 1 / -1;
  }

  .recent-task-actions {
    justify-content: flex-end;
    margin-left: 0;
  }
}

.recent-tasks-pagination {
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 52px;
  padding: 6px 12px;
  border-top: 1px solid #f0f0f0;
}

.recent-tasks-page-size-control,
.recent-tasks-pagination-right {
  display: flex;
  align-items: center;
}

.recent-tasks-page-size-control {
  gap: 8px;
}

.recent-tasks-page-size {
  min-width: 64px;
}

.recent-tasks-pagination-right {
  gap: 12px;
}

.recent-tasks-page-summary {
  white-space: nowrap;
}

.recent-tasks-page-buttons {
  border: 1px solid #e5e7eb;
  border-radius: 4px;
}

body.body--dark .recent-tasks-page-buttons {
  border-color: #3a3f47;
}

body.body--dark .active-tasks-header-row {
  color: #98a2b8;
}

.active-tasks-header-row {
  display: grid;
  grid-template-columns: 168px minmax(140px, 0.55fr) minmax(260px, 1.45fr) 92px;
  gap: 12px;
  align-items: center;
  padding: 0 12px 6px 42px;
  color: #667085;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

@media (max-width: 1023px) {
  .recent-tasks-pagination {
    flex-wrap: wrap;
    justify-content: center;
  }

  .recent-tasks-pagination-right {
    flex-wrap: wrap;
    justify-content: center;
  }

  .active-tasks-header-row {
    display: none;
  }
}

@media (max-width: 599px) {
  .recent-tasks-filters {
    grid-template-columns: minmax(0, 1fr);
  }

  .recent-task-search,
  .recent-tasks-filters :deep(.execution-date-filters),
  .recent-task-actions {
    grid-column: auto;
  }

  .recent-task-actions,
  .recent-task-actions :deep(.q-btn) {
    width: 100%;
  }

  .recent-tasks-content {
    padding-right: 8px;
    padding-left: 8px;
  }

  .recent-tasks-pagination {
    gap: 8px;
    padding: 8px;
  }
}
</style>
