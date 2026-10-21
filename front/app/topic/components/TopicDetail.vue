<template>
  <component :is="embedded ? 'div' : QPage" class="q-pa-md topic-detail-page">
    <PageHeader v-if="!embedded" :icon="navigationIcon('folder_copy')"
      :title="content?.topic.title || t('topic.detail.title')"
      :description="t('topic.detail.subtitle')"
    />

    <div class="row items-center q-gutter-sm q-mb-sm">
      <q-btn
        v-if="!embedded"
        outline
        color="primary"
        no-caps
        icon="arrow_back"
        :label="t('common.back')"
        @click="router.push('/topic')"
      />
      <q-btn
        outline
        color="primary"
        round
        icon="refresh"
        :loading="loading"
        :aria-label="t('topic.refresh')"
        @click="load"
      >
        <q-tooltip>{{ t('topic.refresh') }}</q-tooltip>
      </q-btn>
      <CopyResourceReference v-if="content" :uri="`galaris://topic/${topicId}`" />
      <ResourceReferenceMenu v-if="content" :uri="`galaris://topic/${topicId}`" :title="content.topic.title" target=".topic-detail-page" />
    </div>

    <q-banner v-if="error" rounded class="bg-red-1 text-negative q-mb-md">
      <template #avatar><q-icon name="error_outline" /></template>
      {{ error }}
      <template #action><q-btn outline :label="t('common.retry')" @click="load" /></template>
    </q-banner>

    <template v-if="content">
      <q-card flat bordered class="q-mb-md topic-overview-card">
        <q-card-section>
          <div v-if="content.topic.description" class="text-body1 q-mb-sm">
            {{ content.topic.description }}
          </div>
          <div v-if="content.topic.keywords.length" class="row q-gutter-xs q-mb-sm">
            <q-chip
              v-for="keyword in content.topic.keywords"
              :key="keyword"
              dense
              color="deep-purple-1"
              text-color="deep-purple-9"
            >
              {{ keyword }}
            </q-chip>
          </div>
          <div class="text-caption text-grey-7">
            {{ t('topic.detail.updatedAt', { date: formatDate(content.topic.updated_at || content.topic.created_at) }) }}
          </div>
        </q-card-section>
      </q-card>

      <div class="row q-col-gutter-sm q-mb-md">
        <div
          v-for="metric in metrics"
          :key="metric.key"
          class="col-6 col-md-4 col-lg-2"
        >
          <q-card flat bordered class="full-height topic-metric-card">
            <q-card-section class="row items-center no-wrap q-pa-sm">
              <q-avatar :icon="metric.icon" :color="metric.color" text-color="white" size="34px"
                :style="metric.key === 'datasets' ? { backgroundColor: 'var(--solaire-iris-accent)' } : undefined" />
              <div class="q-ml-sm metric-copy">
                <div class="text-h6">{{ metric.value }}</div>
                <div class="text-caption text-grey-7 ellipsis">{{ metric.label }}</div>
              </div>
            </q-card-section>
          </q-card>
        </div>
      </div>

      <q-card flat bordered class="topic-content-card">
        <q-tabs
          v-model="activeTab"
          dense
          align="left"
          class="text-grey-7 topic-detail-tabs"
          active-color="primary"
          indicator-color="primary"
          outside-arrows
          mobile-arrows
        >
          <q-tab name="spaces" icon="hub" :label="t('topic.detail.participants')" />
          <q-tab name="tasks" icon="task_alt" :label="t('topic.detail.tasks')" />
          <q-tab name="memories" icon="memory" :label="t('topic.detail.memories')" />
        </q-tabs>
        <q-separator />

        <q-tab-panels v-model="activeTab" animated class="bg-transparent">
          <q-tab-panel name="tasks" class="q-pa-none">
            <TopicSectionLimit :shown="content.tasks.length" :total="content.summary.tasks" />
            <q-list v-if="content.tasks.length" separator>
              <q-item v-for="task in content.tasks" :key="task.id" clickable
                @click="openTarget('task', task.id, task.label)">
                <q-item-section avatar><q-icon name="task_alt" color="primary" /></q-item-section>
                <q-item-section>
                  <q-item-label class="text-weight-medium">{{ task.label }}</q-item-label>
                  <q-item-label v-if="task.objective" caption lines="2">{{ richTextExcerpt(task.objective) }}</q-item-label>
                  <q-item-label caption>
                    {{ task.agent_name || t('task.list.noAgent') }} · {{ formatDate(task.created_at) }}
                  </q-item-label>
                </q-item-section>
                <q-item-section side class="topic-item-side">
                  <q-badge :color="statusColor(task.status)">{{ taskStatus(task.status) }}</q-badge>
                </q-item-section>
              </q-item>
            </q-list>
            <div v-else class="topic-empty">{{ t('topic.detail.noTasks') }}</div>
          </q-tab-panel>

          <q-tab-panel name="memories" class="q-pa-none">
            <TopicSectionLimit :shown="content.memories.length" :total="content.summary.memories" />
            <q-list v-if="content.memories.length" separator>
              <q-item v-for="memory in content.memories" :key="memory.id" clickable
                @click="openTarget('memory', memory.id, memory.title, memory.owner_agent_id)">
                <q-item-section avatar><q-icon name="memory" color="deep-purple" /></q-item-section>
                <q-item-section>
                  <q-item-label>{{ memory.title }}</q-item-label>
                  <q-item-label v-if="memory.excerpt" caption lines="2">{{ memory.excerpt }}</q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
            <div v-else class="topic-empty">{{ t('topic.detail.noMemories') }}</div>
          </q-tab-panel>

          <q-tab-panel name="spaces" class="q-pa-md">
            <div class="row q-col-gutter-md">
              <div class="col-12 col-lg-6">
                <div class="text-subtitle1 q-mb-sm">{{ t('topic.detail.rooms') }}</div>
                <TopicSectionLimit :shown="content.rooms.length" :total="content.summary.rooms" />
                <q-list v-if="content.rooms.length" bordered separator class="rounded-borders">
                  <q-item v-for="room in content.rooms" :key="room.id" clickable
                    @click="openTarget('room', room.id, room.label || room.external_id)">
                    <q-item-section avatar>
                      <q-icon :name="room.conversation_type === 'audio' ? 'phone_in_talk' : 'forum'" color="primary" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>{{ room.label || room.external_id }}</q-item-label>
                      <q-item-label caption>{{ t('topic.detail.roomKind', { kind: room.kind, type: room.conversation_type }) }}</q-item-label>
                    </q-item-section>
                  </q-item>
                </q-list>
                <div v-else class="topic-empty topic-empty--bordered">{{ t('topic.detail.noRooms') }}</div>
              </div>

              <div class="col-12 col-lg-6">
                <div class="text-subtitle1 q-mb-sm">{{ t('topic.detail.documents') }}</div>
                <TopicSectionLimit :shown="content.documents.length" :total="content.summary.documents" />
                <q-list v-if="content.documents.length" bordered separator class="rounded-borders q-mb-md">
                  <q-item v-for="document in content.documents" :key="document.id" clickable
                    @click="openTarget('document', document.id, document.title)">
                    <q-item-section avatar><DocumentIcon :document-id="document.id" :title="document.title" /></q-item-section>
                    <q-item-section>
                      <q-item-label>{{ document.title }}</q-item-label>
                      <q-item-label v-if="document.filename" caption>{{ document.filename }}</q-item-label>
                    </q-item-section>
                  </q-item>
                </q-list>
                <div v-else class="topic-empty topic-empty--bordered q-mb-md">{{ t('topic.detail.noDocuments') }}</div>

                <div class="text-subtitle1 q-mb-sm">{{ t('topic.detail.datasets') }}</div>
                <TopicSectionLimit :shown="content.datasets?.length || 0" :total="content.summary.datasets || 0" />
                <q-list v-if="content.datasets?.length" bordered separator class="rounded-borders q-mb-md">
                  <q-item v-for="dataset in content.datasets" :key="dataset.id" clickable
                    @click="openTarget('dataset', dataset.id, dataset.title)">
                    <q-item-section avatar><q-icon name="data_object" style="color: var(--solaire-iris-accent)" /></q-item-section>
                    <q-item-section><q-item-label>{{ dataset.title }}</q-item-label></q-item-section>
                  </q-item>
                </q-list>
                <div v-else class="topic-empty topic-empty--bordered q-mb-md">{{ t('topic.detail.noDatasets') }}</div>
              </div>
            </div>
          </q-tab-panel>
        </q-tab-panels>
      </q-card>
    </template>

    <div v-else-if="loading" class="flex flex-center q-pa-xl">
      <q-spinner color="primary" size="42px" />
    </div>
    <ResourceDetailDialog v-if="selectedTarget" :target="selectedTarget"
      @close="selectedTarget = null" @changed="load" />
  </component>
</template>

<script setup lang="ts">
import { WorkingDocumentIcon as DocumentIcon } from '@/core/util'
import { navigationIcon } from '@/core/navigation'
import { computed, defineComponent, h, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { QPage } from 'quasar'
import { CopyResourceReference, ResourceReferenceMenu, PageHeader, ResourceDetailDialog, richTextExcerpt } from '@/core/util'
import { topicService } from '../services/topicService'
import type { TopicContent, TopicTarget } from '../types'

type DetailTab = 'tasks' | 'memories' | 'spaces'

const { topicId, embedded = false } = defineProps<{ topicId: string; embedded?: boolean }>()
const emit = defineEmits<{ loaded: [title: string] }>()
const router = useRouter()
const { t, te, locale } = useI18n()
const content = ref<TopicContent | null>(null)
const loading = ref(false)
const error = ref('')
const activeTab = ref<DetailTab>('spaces')
const selectedTarget = ref<TopicTarget | null>(null)

const metrics = computed(() => content.value ? [
  { key: 'rooms', label: t('topic.detail.rooms'), value: content.value.summary.rooms, icon: 'meeting_room', color: 'blue-grey' },
  { key: 'tasks', label: t('topic.detail.tasks'), value: content.value.summary.tasks, icon: 'task_alt', color: 'primary' },
  { key: 'memories', label: t('topic.detail.memories'), value: content.value.summary.memories, icon: 'memory', color: 'deep-purple' },
  { key: 'documents', label: t('topic.detail.documents'), value: content.value.summary.documents, icon: 'description', color: 'secondary' },
  { key: 'datasets', label: t('topic.detail.datasets'), value: content.value.summary.datasets || 0, icon: 'data_object', color: undefined },
] : [])

const TopicSectionLimit = defineComponent({
  props: { shown: { type: Number, required: true }, total: { type: Number, required: true } },
  setup(props) {
    return () => props.total > props.shown
      ? h('div', { class: 'text-caption text-grey-7 q-px-md q-py-sm' }, t('topic.detail.recentLimit', { count: props.shown, total: props.total }))
      : null
  },
})

async function load(): Promise<void> {
  if (!topicId) return
  const id = topicId, current = ++generation
  loading.value = true
  error.value = ''
  try {
    const result = await topicService.content(id)
    if (current === generation) { content.value = result; emit('loaded', result.topic.title) }
  } catch {
    if (current === generation) { content.value = null; error.value = t('topic.detail.loadError') }
  } finally {
    if (current === generation) loading.value = false
  }
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function statusColor(status: string): string {
  if (['SUCCESS', 'SUCCEEDED', 'COMPLETED'].includes(status)) return 'positive'
  if (['ERROR', 'ERROR_RESOLVED', 'FAILED'].includes(status)) return 'negative'
  if (['RUNNING', 'CLAIMED', 'FROZEN', 'EXEC', 'PLAN', 'DISPATCH'].includes(status)) return 'primary'
  return 'grey-7'
}

function statusLabel(status: string): string {
  for (const key of [`task.status.${status}`, `conversation.history.detail.roundStatuses.${status}`, `voice.history.turnStatuses.${status}`]) {
    if (te(key)) return t(key)
  }
  return status
}

function taskStatus(status: string): string {
  return statusLabel(status)
}

function openTarget(kind: TopicTarget['kind'], id: string, title: string, agentId?: number | null): void {
  selectedTarget.value = { kind, id, title, agentId }
}

let generation = 0
watch(() => topicId, (_, __, onCleanup) => {
  onCleanup(() => { generation++ })
  selectedTarget.value = null; content.value = null; void load()
}, { immediate: true })
</script>

<style scoped>
.topic-detail-page,
.topic-overview-card,
.topic-content-card {
  min-width: 0;
}

.metric-copy {
  min-width: 0;
}

.topic-detail-tabs {
  max-width: 100%;
}

.topic-item-side {
  align-items: flex-end;
  gap: 4px;
}

.topic-empty {
  padding: 32px 16px;
  color: #757575;
  text-align: center;
}

.topic-empty--bordered {
  border: 1px dashed #cfd8dc;
  border-radius: 4px;
}

body.body--dark .topic-empty--bordered {
  border-color: #455a64;
}

@media (max-width: 600px) {
  .topic-detail-page {
    padding: 12px;
  }

  .topic-item-side {
    align-self: flex-start;
  }
}
</style>
