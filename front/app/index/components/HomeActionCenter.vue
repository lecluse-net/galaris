<template>
  <q-page class="home-page q-pa-md">
    <PageHeader :icon="navigationIcon('dashboard')"
      :title="t('nav.home')"
      :description="t('nav.home_desc')"
    >
      <template #actions>
        <q-btn
          round
          flat
          color="primary"
          icon="refresh"
          :loading="homeLoading"
          :aria-label="t('index.actionCenter.refresh')"
          @click="refresh"
        >
          <q-tooltip>{{ t('index.actionCenter.refresh') }}</q-tooltip>
        </q-btn>
      </template>
    </PageHeader>

    <div class="home-shell">
      <section class="home-hero">
        <div>
          <p class="home-eyebrow">{{ t('index.actionCenter.eyebrow') }}</p>
          <h1>{{ t('index.actionCenter.greeting', { name: authStore.userDisplayName }) }}</h1>
          <p>{{ attentionSummary }}</p>
        </div>
        <div class="home-hero__mark" aria-hidden="true">
          <q-icon :name="unreadCount > 0 ? 'mark_email_unread' : 'done_all'" />
        </div>
      </section>

      <section v-if="canSeeDashboard" class="home-metrics" aria-labelledby="home-metrics-title">
        <div class="home-section-heading">
          <div>
            <h2 id="home-metrics-title">{{ t('index.actionCenter.metrics.title') }}</h2>
            <p>{{ t('index.actionCenter.metrics.description') }}</p>
          </div>
          <q-btn
            flat
            no-caps
            color="primary"
            icon-right="arrow_forward"
            :label="t('index.actionCenter.metrics.more')"
            to="/dashboard"
          />
        </div>

        <q-banner v-if="dashboardStore.error" dense rounded class="metrics-warning">
          <template #avatar><q-icon name="sync_problem" color="warning" /></template>
          {{ t('index.actionCenter.metrics.loadError') }}
        </q-banner>

        <div v-if="dashboardStore.data" class="home-metrics__grid">
          <DashboardMetricCard
            :label="t('index.dashboard.monthlyCost')"
            :value="formatCurrency(dashboardStore.data.totals.cost)"
            icon="payments"
            tone="amber"
            :trend="trend(dashboardStore.data.totals.cost, dashboardStore.data.previous_totals.cost)"
            :hint="t('index.dashboard.vsPrevious')"
            :detail="apiCostDetail(dashboardStore.data.totals.cost, dashboardStore.data.totals.inference_cost)"
            inverse-trend
          />
          <DashboardMetricCard
            :label="t('index.dashboard.consumedTokens')"
            :value="formatCompact(dashboardStore.data.totals.tokens)"
            icon="data_usage"
            tone="violet"
            :trend="trend(dashboardStore.data.totals.tokens, dashboardStore.data.previous_totals.tokens)"
            :hint="t('index.dashboard.vsPrevious')"
          />
        </div>

        <div v-else class="home-metrics__grid" :aria-label="t('index.actionCenter.metrics.loading')">
          <q-skeleton v-for="index in 2" :key="index" type="rect" height="132px" class="metrics-skeleton" />
        </div>
      </section>

      <div
        v-if="canReadChat || canSeeQuickActions"
        class="home-grid"
        :class="{ 'home-grid--single': !canReadChat || !canSeeQuickActions }"
      >
        <q-card v-if="canReadChat" flat class="home-card attention-card">
          <q-card-section class="card-heading">
            <div class="card-heading__icon card-heading__icon--primary">
              <q-icon name="inbox" />
            </div>
            <div>
              <h2>{{ t('index.actionCenter.attention.title') }}</h2>
              <p>{{ t('index.actionCenter.attention.description') }}</p>
            </div>
            <q-badge v-if="unreadCount > 0" rounded color="primary" :label="unreadCountLabel" />
          </q-card-section>
          <q-separator />

          <q-card-section v-if="!privilegeStore.loaded || unreadLoading" class="loading-state">
            <q-spinner color="primary" size="32px" />
            <span>{{ t('index.actionCenter.attention.loading') }}</span>
          </q-card-section>

          <q-card-section v-else-if="unreadError" class="empty-state empty-state--error">
            <q-icon name="cloud_off" />
            <strong>{{ t('index.actionCenter.attention.errorTitle') }}</strong>
            <span>{{ t('index.actionCenter.attention.errorText') }}</span>
            <q-btn flat no-caps color="negative" icon="refresh" :label="t('index.actionCenter.retry')" @click="loadConversations" />
          </q-card-section>

          <q-list v-else-if="unreadConversations.length" separator class="unread-list">
            <q-item
              v-for="room in visibleUnreadConversations"
              :key="room.id"
              clickable
              :to="{ path: '/chat', query: { room: room.id } }"
              class="unread-item"
            >
              <q-item-section avatar>
                <q-avatar color="secondary" text-color="white" icon="forum" />
              </q-item-section>
              <q-item-section>
                <q-item-label class="unread-item__title">
                  <span class="ellipsis">{{ room.label }}</span>
                  <q-badge
                    outline
                    color="grey-7"
                    class="unread-item__messenger"
                    :label="room.messenger_label"
                  />
                </q-item-label>
                <q-item-label caption lines="1">
                  {{ t('index.actionCenter.attention.withAgent', { agent: room.agent_name }) }}
                  <template v-if="room.last_message"> · {{ formatDate(room.last_message.created_at) }}</template>
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-badge rounded color="primary" :label="room.unread_count > 99 ? '99+' : room.unread_count" />
              </q-item-section>
            </q-item>
          </q-list>

          <q-card-section v-else class="empty-state empty-state--success">
            <q-icon name="task_alt" />
            <strong>{{ t('index.actionCenter.attention.emptyTitle') }}</strong>
            <span>{{ t('index.actionCenter.attention.emptyText') }}</span>
          </q-card-section>

          <q-separator v-if="canReadChat" />
          <q-card-actions v-if="canReadChat" align="right">
            <q-btn flat no-caps color="primary" icon-right="arrow_forward" :label="t('index.actionCenter.attention.openChat')" to="/chat" />
          </q-card-actions>
        </q-card>

        <q-card v-if="canSeeQuickActions" flat class="home-card quick-card">
          <q-card-section class="card-heading">
            <div class="card-heading__icon card-heading__icon--accent">
              <q-icon name="bolt" />
            </div>
            <div>
              <h2>{{ t('index.actionCenter.quick.title') }}</h2>
              <p>{{ t('index.actionCenter.quick.description') }}</p>
            </div>
          </q-card-section>
          <q-separator />
          <q-card-section class="quick-actions">
            <q-btn v-if="canReadAgents" outline no-caps color="primary" icon="people" :label="t('index.actionCenter.quick.agents')" to="/agent" />
            <q-btn v-if="canReadChat" outline no-caps color="primary" icon="forum" :label="t('index.actionCenter.quick.chat')" to="/chat" />
            <q-btn v-if="canReadTasks" outline no-caps color="primary" icon="monitor_heart" :label="t('index.actionCenter.quick.tasks')" to="/task" />
            <q-btn v-if="canSeeDashboard" outline no-caps color="primary" icon="dashboard" :label="t('index.actionCenter.quick.dashboard')" to="/dashboard" />
          </q-card-section>
        </q-card>
      </div>

      <div
        v-if="canSeeRecentActivity || canReadIncidents"
        class="activity-grid"
        :class="{ 'activity-grid--single': !canSeeRecentActivity || !canReadIncidents }"
      >
        <q-card v-if="canSeeRecentActivity" flat class="home-card activity-card">
          <q-card-section class="card-heading">
            <div class="card-heading__icon card-heading__icon--accent">
              <q-icon name="history" />
            </div>
            <div>
              <h2>{{ t('index.actionCenter.recent.title') }}</h2>
              <p>{{ t('index.actionCenter.recent.description') }}</p>
            </div>
          </q-card-section>
          <q-separator />

          <q-banner v-if="recentActivityError && recentActivities.length" dense class="activity-warning">
            <template #avatar><q-icon name="sync_problem" color="warning" /></template>
            {{ t('index.actionCenter.recent.partialError') }}
          </q-banner>

          <q-card-section v-if="recentActivityLoading && !recentActivities.length" class="loading-state activity-state">
            <q-spinner color="primary" size="32px" />
            <span>{{ t('index.actionCenter.recent.loading') }}</span>
          </q-card-section>

          <q-card-section v-else-if="recentActivityError && !recentActivities.length" class="empty-state empty-state--error activity-state">
            <q-icon name="cloud_off" />
            <strong>{{ t('index.actionCenter.recent.errorTitle') }}</strong>
            <span>{{ t('index.actionCenter.recent.errorText') }}</span>
          </q-card-section>

          <q-list v-else-if="recentActivities.length" separator class="activity-list">
            <q-item
              v-for="activity in recentActivities"
              :key="activity.key"
              clickable
              :to="activity.to"
              class="activity-item"
            >
              <q-item-section avatar>
                <q-avatar :color="activityColor(activity.kind)" text-color="white" :icon="activityIcon(activity.kind)" />
              </q-item-section>
              <q-item-section>
                <q-item-label class="activity-item__title">{{ activity.title }}</q-item-label>
                <q-item-label v-if="activity.detail" caption lines="1">{{ activity.detail }}</q-item-label>
                <q-item-label caption>
                  {{ t(`index.actionCenter.recent.types.${activity.kind}`) }} · {{ formatDate(activity.timestamp) }}
                </q-item-label>
              </q-item-section>
              <q-item-section v-if="activity.badge" side top>
                <q-badge outline color="grey-7" :label="activity.badge" />
              </q-item-section>
            </q-item>
          </q-list>

          <q-card-section v-else class="empty-state activity-state">
            <q-icon name="history_toggle_off" />
            <strong>{{ t('index.actionCenter.recent.emptyTitle') }}</strong>
            <span>{{ t('index.actionCenter.recent.emptyText') }}</span>
          </q-card-section>
        </q-card>

        <q-card v-if="canReadIncidents" flat class="home-card incident-card">
          <q-card-section class="card-heading">
            <div class="card-heading__icon incident-heading-icon">
              <q-icon name="error_outline" />
            </div>
            <div>
              <h2>{{ t('index.actionCenter.incidents.title') }}</h2>
              <p>{{ t('index.actionCenter.incidents.description') }}</p>
            </div>
            <q-badge v-if="incidentTotal > 0" rounded color="negative" :label="incidentTotal" />
          </q-card-section>
          <q-separator />

          <q-card-section v-if="incidentLoading" class="loading-state activity-state">
            <q-spinner color="negative" size="32px" />
            <span>{{ t('index.actionCenter.incidents.loading') }}</span>
          </q-card-section>

          <q-card-section v-else-if="incidentError" class="empty-state empty-state--error activity-state">
            <q-icon name="cloud_off" />
            <strong>{{ t('index.actionCenter.incidents.errorTitle') }}</strong>
            <span>{{ t('index.actionCenter.incidents.errorText') }}</span>
          </q-card-section>

          <q-list v-else-if="recentIncidents.length" separator class="activity-list">
            <q-item
              v-for="incident in recentIncidents"
              :key="incident.id"
              clickable
              to="/incident"
              class="activity-item"
            >
              <q-item-section avatar>
                <q-avatar color="negative" text-color="white" icon="warning_amber" />
              </q-item-section>
              <q-item-section>
                <q-item-label class="activity-item__title">{{ incidentKindLabel(incident.kind) }}</q-item-label>
                <q-item-label caption>{{ formatDate(incident.occurred_at) }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-badge
                  :color="incident.recovered_at ? 'positive' : 'negative'"
                  :label="incident.recovered_at ? t('index.actionCenter.incidents.recovered') : t('index.actionCenter.incidents.open')"
                />
              </q-item-section>
            </q-item>
          </q-list>

          <q-card-section v-else class="empty-state empty-state--success activity-state">
            <q-icon name="verified" />
            <strong>{{ t('index.actionCenter.incidents.emptyTitle') }}</strong>
            <span>{{ t('index.actionCenter.incidents.emptyText') }}</span>
          </q-card-section>

          <q-separator />
          <q-card-actions align="right">
            <q-btn flat no-caps color="negative" icon-right="arrow_forward" :label="t('index.actionCenter.incidents.openLog')" to="/incident" />
          </q-card-actions>
        </q-card>
      </div>

    </div>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { useAuthStore } from '@/core/user'
import { PageHeader } from '@/core/util'
import { useOnboardingStore } from '@/app/onboarding'
import { useDashboardStore } from '../stores/dashboardStore'
import DashboardMetricCard from './DashboardMetricCard.vue'
import {
  homeService,
  type HomeConversation,
  type HomeRecentIncident,
} from '../services/homeService'

type ActivityKind = 'message' | 'task' | 'process' | 'memory'

interface HomeActivity {
  key: string
  kind: ActivityKind
  title: string
  detail: string
  timestamp: string
  to: string
  badge?: string
}

const { t, locale } = useI18n()
const authStore = useAuthStore()
const privilegeStore = usePrivilegeStore()
const onboardingStore = useOnboardingStore()
const dashboardStore = useDashboardStore()
const unreadConversations = ref<HomeConversation[]>([])
const conversationActivities = ref<HomeActivity[]>([])
const domainActivities = ref<HomeActivity[]>([])
const recentIncidents = ref<HomeRecentIncident[]>([])
const incidentTotal = ref(0)
const unreadLoading = ref(false)
const unreadError = ref(false)
const domainActivityLoading = ref(false)
const domainActivityError = ref(false)
const incidentLoading = ref(false)
const incidentError = ref(false)

const canReadAgents = computed(() => privilegeStore.hasPrivilege(privileges.AGENT_ACCESS))
const canReadChat = computed(() => privilegeStore.hasPrivilege(privileges.CHAT_ACCESS))
const canReadTasks = computed(() => (
  privilegeStore.hasPrivilege(privileges.TASK_ACCESS)
  || privilegeStore.hasPrivilege(privileges.TASK_EDIT)
))
const canReadProcesses = computed(() => (
  privilegeStore.hasPrivilege(privileges.PROCESS_READ)
  || privilegeStore.hasPrivilege(privileges.PROCESS_LAUNCH)
  || privilegeStore.hasPrivilege(privileges.PROCESS_ADMIN)
))
const canReadMemory = computed(() => (
  privilegeStore.hasPrivilege(privileges.MEMORY_ACCESS)
  || privilegeStore.hasPrivilege(privileges.MEMORY_EDIT)
  || privilegeStore.hasPrivilege(privileges.MEMORY_ADMIN)
))
const canReadIncidents = computed(() => privilegeStore.hasPrivilege(privileges.INCIDENT_ACCESS))
const canSeeDashboard = canReadTasks
const canSeeQuickActions = computed(() => (
  canReadAgents.value || canReadChat.value || canReadTasks.value
))
const canSeeRecentActivity = computed(() => (
  canReadChat.value
  || canReadTasks.value
  || canReadProcesses.value
  || canReadMemory.value
))
const unreadCount = computed(() => (
  unreadConversations.value.reduce((total, room) => total + room.unread_count, 0)
))
const visibleUnreadConversations = computed(() => unreadConversations.value.slice(0, 5))
const unreadCountLabel = computed(() => t('index.actionCenter.attention.unreadCount', { count: unreadCount.value }))
const attentionSummary = computed(() => unreadCount.value > 0
  ? t('index.actionCenter.summaryUnread', { count: unreadCount.value })
  : t('index.actionCenter.summaryClear'))
const recentActivities = computed(() => (
  [...conversationActivities.value, ...domainActivities.value]
    .sort((left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp))
    .slice(0, 12)
))
const recentActivityLoading = computed(() => (
  (canReadChat.value && unreadLoading.value) || domainActivityLoading.value
))
const recentActivityError = computed(() => (
  (canReadChat.value && unreadError.value) || domainActivityError.value
))
const homeLoading = computed(() => (
  unreadLoading.value
  || domainActivityLoading.value
  || incidentLoading.value
  || dashboardStore.loading
))
const activityAccessKey = computed(() => [
  canReadChat.value,
  canReadTasks.value,
  canReadProcesses.value,
  canReadMemory.value,
  canReadIncidents.value,
].join(':'))
function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function formatCurrency(value: number): string {
  return Intl.NumberFormat(locale.value, {
    style: 'currency',
    currency: 'USD',
    currencyDisplay: 'narrowSymbol',
    minimumFractionDigits: 2,
    maximumFractionDigits: value < 1 ? 4 : 2,
  }).format(value)
}

function formatCompact(value: number): string {
  return Intl.NumberFormat(locale.value, { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function trend(current: number, previous: number): number | null {
  if (previous === 0) return current === 0 ? 0 : null
  return ((current - previous) / previous) * 100
}

function apiCostDetail(billedCost: number, apiCost: number): string | undefined {
  const billed = formatCurrency(billedCost)
  const equivalent = formatCurrency(apiCost)
  if (billed === equivalent) return undefined
  return t('index.dashboard.apiEquivalent', { cost: equivalent })
}

function activityIcon(kind: ActivityKind): string {
  if (kind === 'message') return 'forum'
  if (kind === 'task') return 'task_alt'
  if (kind === 'process') return 'account_tree'
  return 'neurology'
}

function activityColor(kind: ActivityKind): string {
  if (kind === 'message') return 'secondary'
  if (kind === 'task') return 'primary'
  if (kind === 'process') return 'accent'
  return 'positive'
}

function incidentKindLabel(kind: string): string {
  if (kind === 'llm') return t('index.actionCenter.incidents.kinds.llm')
  if (kind === 'tool') return t('index.actionCenter.incidents.kinds.tool')
  return t('index.actionCenter.incidents.kinds.other')
}

async function loadConversations(): Promise<void> {
  if (!canReadChat.value) {
    unreadConversations.value = []
    conversationActivities.value = []
    unreadError.value = false
    return
  }
  if (unreadLoading.value) return
  unreadLoading.value = true
  unreadError.value = false
  try {
    const rooms = await homeService.getRecentConversations()
    unreadConversations.value = rooms.filter(room => room.unread_count > 0)
    conversationActivities.value = rooms.flatMap((room): HomeActivity[] => {
      if (!room.last_message) return []
      return [{
        key: `message:${room.id}:${room.last_message.created_at}`,
        kind: 'message',
        title: room.label,
        detail: room.last_message.text.trim() || t('index.actionCenter.recent.messageWithoutText'),
        timestamp: room.last_message.created_at,
        to: `/chat?room=${encodeURIComponent(room.id)}`,
        badge: room.messenger_label,
      }]
    })
  } catch (error) {
    unreadError.value = true
    unreadConversations.value = []
    conversationActivities.value = []
    console.error('Unable to load recent conversations:', error)
  } finally {
    unreadLoading.value = false
  }
}

async function loadDomainActivities(): Promise<void> {
  const requests: Array<Promise<HomeActivity[]>> = []
  if (canReadTasks.value) {
    requests.push(homeService.getRecentTasks().then(tasks => tasks.map(task => ({
      key: `task:${task.id}`,
      kind: 'task' as const,
      title: task.label,
      detail: t('index.actionCenter.recent.events.task'),
      timestamp: task.created_at,
      to: `/task?tab=tasks&task_id=${encodeURIComponent(task.id)}`,
    }))))
  }
  if (canReadProcesses.value) {
    requests.push(homeService.getRecentProcesses().then(processes => processes.map(process => ({
      key: `process:${process.id}`,
      kind: 'process' as const,
      title: process.process_label || process.workflow_id || t('index.actionCenter.recent.processFallback'),
      detail: t('index.actionCenter.recent.events.process'),
      timestamp: process.created_at,
      to: '/process',
    }))))
  }
  if (canReadMemory.value) {
    requests.push(homeService.getRecentMemories().then(memories => memories.map(memory => ({
      key: `memory:${memory.id}`,
      kind: 'memory' as const,
      title: memory.title,
      detail: t('index.actionCenter.recent.events.memory'),
      timestamp: memory.created_at,
      to: '/memory',
    }))))
  }
  if (!requests.length) {
    domainActivities.value = []
    domainActivityError.value = false
    return
  }

  domainActivityLoading.value = true
  domainActivityError.value = false
  try {
    const results = await Promise.allSettled(requests)
    domainActivities.value = results.flatMap(result => (
      result.status === 'fulfilled' ? result.value : []
    ))
    domainActivityError.value = results.some(result => result.status === 'rejected')
  } finally {
    domainActivityLoading.value = false
  }
}

async function loadIncidents(): Promise<void> {
  if (!canReadIncidents.value) {
    recentIncidents.value = []
    incidentTotal.value = 0
    incidentError.value = false
    return
  }
  if (incidentLoading.value) return
  incidentLoading.value = true
  incidentError.value = false
  try {
    const result = await homeService.getRecentIncidents()
    recentIncidents.value = result.items
    incidentTotal.value = result.total
  } catch (error) {
    recentIncidents.value = []
    incidentTotal.value = 0
    incidentError.value = true
    console.error('Unable to load recent incidents:', error)
  } finally {
    incidentLoading.value = false
  }
}

async function loadDashboardMetrics(): Promise<void> {
  if (!canSeeDashboard.value || dashboardStore.loading) return
  await dashboardStore.fetchDashboard()
}

async function refreshHomeData(): Promise<void> {
  await Promise.all([
    loadConversations(),
    loadDomainActivities(),
    loadIncidents(),
    loadDashboardMetrics(),
  ])
}

function refresh(): void {
  void onboardingStore.fetchOverview()
  void refreshHomeData()
}

watch(
  [() => privilegeStore.loaded, activityAccessKey],
  ([loaded]) => {
    if (loaded) void refreshHomeData()
  },
  { immediate: true },
)
</script>

<style scoped>
.home-page {
  --home-surface: rgba(255, 255, 255, 0.97);
  --home-text: #263238;
  --home-muted: #6b7280;
  --home-border: rgba(0, 0, 0, 0.1);
  --home-shadow: rgba(0, 0, 0, 0.07);
  min-height: 100vh;
}

.home-shell { width: min(1240px, 100%); margin: 0 auto; }

.home-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 24px;
  align-items: center;
  overflow: hidden;
  margin-bottom: 20px;
  padding: clamp(24px, 4vw, 42px);
  color: white;
  border: 1px solid rgba(76, 217, 210, 0.2);
  border-radius: 24px;
  background-color: #071426;
  background-image:
    linear-gradient(
      90deg,
      rgba(5, 18, 36, 0.88) 0%,
      rgba(5, 18, 36, 0.64) 56%,
      rgba(5, 18, 36, 0.22) 100%
    ),
    url('/background.jpg');
  background-position: center 38%;
  background-size: cover;
  box-shadow: 0 18px 44px rgba(7, 25, 48, 0.18);
}

.home-eyebrow { margin: 0 0 7px; color: #79e1dc; font-size: 0.72rem; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; }
.home-hero h1 { margin: 0; font-size: clamp(1.8rem, 4vw, 2.8rem); letter-spacing: -0.035em; text-shadow: 0 2px 16px rgba(0, 0, 0, 0.22); }
.home-hero p:last-child { max-width: 680px; margin: 12px 0 0; color: rgba(233, 244, 248, 0.84); font-size: 1rem; line-height: 1.6; }
.home-hero__mark { display: grid; width: clamp(84px, 11vw, 126px); height: clamp(84px, 11vw, 126px); place-items: center; color: #72e5df; border: 1px solid rgba(114, 229, 223, 0.28); border-radius: 30px; background: rgba(5, 20, 38, 0.48); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08); backdrop-filter: blur(10px); }
.home-hero__mark .q-icon { font-size: clamp(42px, 6vw, 66px); }

.home-metrics { margin-bottom: 20px; }
.home-section-heading { display: flex; gap: 20px; align-items: center; justify-content: space-between; margin-bottom: 12px; padding: 0 4px; }
.home-section-heading h2 { margin: 0; color: var(--home-text); font-size: 1rem; }
.home-section-heading p { margin: 3px 0 0; color: var(--home-muted); font-size: 0.74rem; line-height: 1.4; }
.home-metrics__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.metrics-warning { margin-bottom: 12px; color: var(--home-muted); background: color-mix(in srgb, var(--q-warning) 10%, var(--home-surface)); }
.metrics-skeleton { border-radius: 18px; }

.home-grid { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(280px, 0.7fr); gap: 20px; margin-bottom: 20px; align-items: start; }
.home-grid--single { grid-template-columns: 1fr; }
.home-card { overflow: hidden; color: var(--home-text); border: 1px solid var(--home-border); border-radius: 19px; background: var(--home-surface); box-shadow: 0 10px 34px var(--home-shadow); }
.card-heading { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 13px; align-items: center; padding: 18px 20px; }
.card-heading__icon { display: grid; width: 42px; height: 42px; place-items: center; border-radius: 13px; font-size: 22px; }
.card-heading__icon--primary { color: var(--q-primary); background: color-mix(in srgb, var(--q-primary) 12%, transparent); }
.card-heading__icon--accent { color: var(--q-accent); background: color-mix(in srgb, var(--q-accent) 12%, transparent); }
.card-heading__icon--secondary { color: var(--q-secondary); background: color-mix(in srgb, var(--q-secondary) 12%, transparent); }
.card-heading h2 { margin: 0; color: var(--home-text); font-size: 1rem; }
.card-heading p { margin: 3px 0 0; color: var(--home-muted); font-size: 0.74rem; line-height: 1.4; }

.loading-state,
.empty-state { display: flex; min-height: 210px; flex-direction: column; gap: 9px; align-items: center; justify-content: center; padding: 28px; color: var(--home-muted); text-align: center; }
.empty-state .q-icon { color: var(--home-muted); font-size: 40px; }
.empty-state strong { color: var(--home-text); font-size: 0.95rem; }
.empty-state span { max-width: 430px; font-size: 0.76rem; line-height: 1.55; }
.empty-state--success .q-icon { color: var(--q-positive); }
.empty-state--error .q-icon { color: var(--q-negative); }
.unread-list { min-height: 210px; }
.unread-item { min-height: 67px; padding: 9px 18px; }
.unread-item__title { display: flex; min-width: 0; gap: 7px; align-items: center; color: var(--home-text); font-weight: 750; }
.unread-item__messenger { flex: 0 0 auto; font-size: 0.6rem; font-weight: 500; }
.quick-actions { display: grid; gap: 10px; padding: 18px; }
.quick-actions .q-btn { justify-content: flex-start; min-height: 42px; }

.activity-grid { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(300px, 0.7fr); gap: 20px; margin-bottom: 20px; align-items: start; }
.activity-grid--single { grid-template-columns: 1fr; }
.activity-card,
.incident-card { min-width: 0; }
.activity-list { min-height: 190px; }
.activity-state { min-height: 190px; }
.activity-item { min-height: 68px; padding: 9px 18px; }
.activity-item__title { color: var(--home-text); font-weight: 700; }
.activity-warning { color: var(--home-muted); background: color-mix(in srgb, var(--q-warning) 10%, transparent); }
.incident-heading-icon { color: var(--q-negative); background: color-mix(in srgb, var(--q-negative) 12%, transparent); }

body.body--dark .home-page {
  --home-surface: rgba(29, 29, 29, 0.97);
  --home-text: rgba(255, 255, 255, 0.9);
  --home-muted: rgba(255, 255, 255, 0.62);
  --home-border: rgba(255, 255, 255, 0.09);
  --home-shadow: rgba(0, 0, 0, 0.35);
}

body.body--dark .home-hero {
  border-color: rgba(92, 220, 214, 0.14);
  background-image:
    linear-gradient(
      90deg,
      rgba(2, 7, 16, 0.92) 0%,
      rgba(2, 9, 20, 0.72) 56%,
      rgba(2, 9, 20, 0.38) 100%
    ),
    url('/background.jpg');
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.45);
}

body.body--dark .home-hero__mark {
  border-color: rgba(114, 229, 223, 0.18);
  background: rgba(2, 8, 18, 0.6);
}

@media (max-width: 1023px) {
  .home-grid,
  .activity-grid { grid-template-columns: 1fr; }
}

@media (max-width: 599px) {
  .home-hero { grid-template-columns: 1fr; }
  .home-hero__mark { display: none; }
  .home-section-heading { align-items: flex-start; }
  .home-metrics__grid { grid-template-columns: 1fr; }
  .card-heading { grid-template-columns: auto minmax(0, 1fr); }
  .card-heading > .q-badge { grid-column: 2; justify-self: start; }
}
</style>
