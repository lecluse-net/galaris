<template>
  <q-page class="q-pa-md topic-detail-page">
    <q-btn
      flat
      dense
      icon="arrow_back"
      :label="t('common.back')"
      class="q-mb-sm"
      @click="router.push('/topic')"
    />

    <PageHeader :icon="navigationIcon('folder_copy')"
      :title="content?.topic.title || t('topic.detail.title')"
      :description="t('topic.detail.subtitle')"
    >
      <template #title-after>
        <q-btn
          flat
          round
          color="primary"
          icon="refresh"
          :loading="loading"
          :aria-label="t('topic.refresh')"
          @click="load"
        />
      </template>
    </PageHeader>

    <q-banner v-if="error" rounded class="bg-red-1 text-negative q-mb-md">
      <template #avatar><q-icon name="error_outline" /></template>
      {{ error }}
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
              <q-avatar :icon="metric.icon" :color="metric.color" text-color="white" size="34px" />
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
          <q-tab name="tasks" icon="task_alt" :label="t('topic.detail.tasks')" />
          <q-tab name="conversations" icon="forum" :label="t('topic.detail.conversationRounds')" />
          <q-tab name="voice" icon="record_voice_over" :label="t('topic.detail.voiceTurns')" />
          <q-tab name="spaces" icon="hub" :label="t('topic.detail.participants')" />
        </q-tabs>
        <q-separator />

        <q-tab-panels v-model="activeTab" animated class="bg-transparent">
          <q-tab-panel name="tasks" class="q-pa-none">
            <TopicSectionLimit :shown="content.tasks.length" :total="content.summary.tasks" />
            <q-list v-if="content.tasks.length" separator>
              <q-item v-for="task in content.tasks" :key="task.id">
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
                  <q-btn
                    flat
                    round
                    dense
                    icon="open_in_new"
                    :aria-label="t('topic.detail.openTask')"
                    @click="openTask(task.id)"
                  />
                </q-item-section>
              </q-item>
            </q-list>
            <div v-else class="topic-empty">{{ t('topic.detail.noTasks') }}</div>
          </q-tab-panel>

          <q-tab-panel name="conversations" class="q-pa-none">
            <TopicSectionLimit :shown="content.conversation_rounds.length" :total="content.summary.conversation_rounds" />
            <RoundList
              :rounds="content.conversation_rounds"
              :empty-label="t('topic.detail.noConversationRounds')"
            />
          </q-tab-panel>

          <q-tab-panel name="voice" class="q-pa-none">
            <TopicSectionLimit :shown="content.voice_turns.length" :total="content.summary.voice_turns" />
            <RoundList
              :rounds="content.voice_turns"
              :empty-label="t('topic.detail.noVoiceTurns')"
              voice
            />
          </q-tab-panel>

          <q-tab-panel name="spaces" class="q-pa-md">
            <div class="row q-col-gutter-md">
              <div class="col-12 col-lg-6">
                <div class="text-subtitle1 q-mb-sm">{{ t('topic.detail.rooms') }}</div>
                <TopicSectionLimit :shown="content.rooms.length" :total="content.summary.rooms" />
                <q-list v-if="content.rooms.length" bordered separator class="rounded-borders">
                  <q-item v-for="room in content.rooms" :key="room.id">
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
                <q-list v-if="content.documents.length" bordered separator class="rounded-borders q-mb-md">
                  <q-item v-for="document in content.documents" :key="document.id">
                    <q-item-section avatar><DocumentIcon :document-id="document.id" :title="document.title" /></q-item-section>
                    <q-item-section>
                      <q-item-label>{{ document.title }}</q-item-label>
                      <q-item-label v-if="document.filename" caption>{{ document.filename }}</q-item-label>
                    </q-item-section>
                  </q-item>
                </q-list>
                <div v-else class="topic-empty topic-empty--bordered q-mb-md">{{ t('topic.detail.noDocuments') }}</div>

                <div class="text-subtitle1 q-mb-sm">{{ t('topic.detail.memories') }}</div>
                <q-list v-if="content.memories.length" bordered separator class="rounded-borders">
                  <q-item v-for="memory in content.memories" :key="memory.id">
                    <q-item-section avatar><q-icon name="memory" color="deep-purple" /></q-item-section>
                    <q-item-section>
                      <q-item-label>{{ memory.title }}</q-item-label>
                      <q-item-label v-if="memory.excerpt" caption lines="2">{{ memory.excerpt }}</q-item-label>
                    </q-item-section>
                  </q-item>
                </q-list>
                <div v-else class="topic-empty topic-empty--bordered">{{ t('topic.detail.noMemories') }}</div>
              </div>
            </div>
          </q-tab-panel>
        </q-tab-panels>
      </q-card>
    </template>

    <div v-else-if="loading" class="flex flex-center q-pa-xl">
      <q-spinner color="primary" size="42px" />
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { WorkingDocumentIcon as DocumentIcon } from '@/core/util'
import { navigationIcon } from '@/core/navigation'
import { computed, defineComponent, h, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { QBadge, QIcon, QItem, QItemLabel, QItemSection, QList } from 'quasar'
import { PageHeader, richTextExcerpt } from '@/core/util'
import { topicService } from '../services/topicService'
import type { TopicContent, TopicRound, TopicVoiceTurn } from '../types'

type DetailTab = 'tasks' | 'conversations' | 'voice' | 'spaces'

const route = useRoute()
const router = useRouter()
const { t, te, locale } = useI18n()
const content = ref<TopicContent | null>(null)
const loading = ref(false)
const error = ref('')
const activeTab = ref<DetailTab>('tasks')

const topicId = computed(() => String(route.params.id || ''))
const metrics = computed(() => content.value ? [
  { key: 'rooms', label: t('topic.detail.rooms'), value: content.value.summary.rooms, icon: 'meeting_room', color: 'blue-grey' },
  { key: 'tasks', label: t('topic.detail.tasks'), value: content.value.summary.tasks, icon: 'task_alt', color: 'primary' },
  { key: 'conversation_rounds', label: t('topic.detail.conversationRounds'), value: content.value.summary.conversation_rounds, icon: 'forum', color: 'teal' },
  { key: 'voice_turns', label: t('topic.detail.voiceTurns'), value: content.value.summary.voice_turns, icon: 'record_voice_over', color: 'orange' },
  { key: 'memories', label: t('topic.detail.memories'), value: content.value.summary.memories, icon: 'memory', color: 'deep-purple' },
  { key: 'documents', label: t('topic.detail.documents'), value: content.value.summary.documents, icon: 'description', color: 'secondary' },
] : [])

const TopicSectionLimit = defineComponent({
  props: { shown: { type: Number, required: true }, total: { type: Number, required: true } },
  setup(props) {
    return () => props.total > props.shown
      ? h('div', { class: 'text-caption text-grey-7 q-px-md q-py-sm' }, t('topic.detail.recentLimit', { count: props.shown, total: props.total }))
      : null
  },
})

const RoundList = defineComponent({
  props: {
    rounds: { type: Array as () => Array<TopicRound | TopicVoiceTurn>, required: true },
    emptyLabel: { type: String, required: true },
    voice: { type: Boolean, default: false },
  },
  setup(props) {
    return () => props.rounds.length
      ? h(QList, { separator: true }, () => props.rounds.map(round => h(QItem, { key: round.id }, () => [
        h(QItemSection, { avatar: true }, () => h(QIcon, { name: props.voice ? 'record_voice_over' : 'forum', color: 'primary' })),
        h(QItemSection, {}, () => [
          h(QItemLabel, { class: 'text-weight-medium' }, () => props.voice && 'sequence' in round
            ? t('topic.detail.voiceTurn', { sequence: round.sequence })
            : round.room_label),
          h(QItemLabel, { caption: true }, () => `${round.room_label} · ${formatDate(round.created_at)}`),
          h(QItemLabel, { caption: true, lines: 2 }, () => `${t('topic.detail.request')}: ${round.preview || t('topic.detail.noPreview')}`),
          round.response ? h(QItemLabel, { caption: true, lines: 2 }, () => `${t('topic.detail.response')}: ${round.response}`) : null,
        ]),
        h(QItemSection, { side: true }, () => h(QBadge, { color: statusColor(round.status) }, () => statusLabel(round.status))),
      ])))
      : h('div', { class: 'topic-empty' }, props.emptyLabel)
  },
})

async function load(): Promise<void> {
  if (!topicId.value) return
  loading.value = true
  error.value = ''
  try {
    content.value = await topicService.content(topicId.value)
  } catch {
    content.value = null
    error.value = t('topic.detail.loadError')
  } finally {
    loading.value = false
  }
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function statusColor(status: string): string {
  if (['SUCCESS', 'SUCCEEDED', 'COMPLETED'].includes(status)) return 'positive'
  if (['ERROR', 'ERROR_RESOLVED', 'FAILED'].includes(status)) return 'negative'
  if (['RUNNING', 'CLAIMED', 'FROZEN', 'EXEC', 'PLAN', 'DISPATCH', 'BRIEFING'].includes(status)) return 'primary'
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

function openTask(id: string): void {
  void router.push({ path: '/task', query: { tab: 'tasks', task_id: id } })
}

onMounted(load)
watch(topicId, load)
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
