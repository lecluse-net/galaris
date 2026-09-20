<template>
  <q-table
    flat
    :rows="agents"
    :columns="columns"
    row-key="agent_id"
    :rows-per-page-options="[0]"
    hide-bottom
    :no-data-label="t('index.dashboard.noAgents')"
    class="agent-table"
  >
    <template #body-cell-agent="scope">
      <q-td :props="scope">
        <div class="agent-cell">
          <q-avatar size="38px" class="agent-avatar">
            <img
              v-if="scope.row.has_avatar && avatarUrls[scope.row.agent_id]"
              :src="avatarUrls[scope.row.agent_id]"
              :alt="scope.row.agent_name"
            />
            <template v-else>{{ initials(scope.row.agent_name) }}</template>
          </q-avatar>
          <div class="agent-identity">
            <span class="agent-name">{{ scope.row.agent_name }}</span>
            <span class="agent-title">{{ scope.row.job_title || t('index.dashboard.agentFallback') }}</span>
          </div>
        </div>
      </q-td>
    </template>

    <template #body-cell-success="scope">
      <q-td :props="scope">
        <div class="success-cell">
          <span>{{ scope.row.tasks ? formatPercent(scope.row.task_success_rate) : '—' }}</span>
          <q-linear-progress
            :value="scope.row.task_success_rate / 100"
            :color="successColor(scope.row.task_success_rate)"
            track-color="grey-3"
            rounded
            size="5px"
          />
        </div>
      </q-td>
    </template>

    <template #body-cell-tokens="scope">
      <q-td :props="scope" class="number-cell">{{ formatCompact(scope.row.tokens) }}</q-td>
    </template>

    <template #body-cell-cost="scope">
      <q-td :props="scope" class="number-cell">{{ formatCurrency(scope.row.cost) }}</q-td>
    </template>

    <template #body-cell-duration="scope">
      <q-td :props="scope" class="number-cell">
        {{ scope.row.llm_calls ? formatDuration(scope.row.average_llm_duration) : '—' }}
      </q-td>
    </template>

    <template #body-cell-incidents="scope">
      <q-td :props="scope">
        <q-badge
          rounded
          :color="scope.row.incidents ? 'negative' : 'positive'"
          :outline="!scope.row.incidents"
          :label="scope.row.incidents"
          class="incident-badge"
        >
          <q-tooltip>
            {{ t('index.dashboard.errorBreakdown', {
              tasks: scope.row.task_errors,
              llm: scope.row.llm_errors,
            }) }}
          </q-tooltip>
        </q-badge>
      </q-td>
    </template>
  </q-table>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, watch } from 'vue'
import { type QTableColumn } from 'quasar'
import { useI18n } from 'vue-i18n'
import { agentService } from '@/app/agent/services/agentService'
import type { AgentUsage } from '../services/dashboardService'

const { agents } = defineProps<{ agents: AgentUsage[] }>()

const { t, locale } = useI18n()
const avatarUrls = reactive<Record<number, string>>({})
const loadingAvatarIds = new Set<number>()
let disposed = false

watch(
  () => agents.map(agent => `${agent.agent_id}:${agent.has_avatar}`).join(','),
  () => { void syncAvatars() },
  { immediate: true },
)

onBeforeUnmount(() => {
  disposed = true
  for (const url of Object.values(avatarUrls)) URL.revokeObjectURL(url)
})

const columns = computed<QTableColumn[]>(() => [
  { name: 'agent', label: t('index.dashboard.agent'), field: 'agent_name', align: 'left', sortable: true },
  { name: 'tasks', label: t('index.dashboard.tasks'), field: 'tasks', align: 'right', sortable: true },
  { name: 'success', label: t('index.dashboard.successRate'), field: 'task_success_rate', align: 'right', sortable: true },
  { name: 'llm_calls', label: t('index.dashboard.llmCalls'), field: 'llm_calls', align: 'right', sortable: true },
  { name: 'tokens', label: t('index.dashboard.tokens'), field: 'tokens', align: 'right', sortable: true },
  { name: 'cost', label: t('index.dashboard.cost'), field: 'cost', align: 'right', sortable: true },
  { name: 'duration', label: t('index.dashboard.avgLatencyShort'), field: 'average_llm_duration', align: 'right', sortable: true },
  { name: 'incidents', label: t('index.dashboard.incidents'), field: 'incidents', align: 'center', sortable: true },
])

async function syncAvatars(): Promise<void> {
  const expectedIds = new Set(
    agents.filter(agent => agent.has_avatar).map(agent => agent.agent_id),
  )
  for (const [rawId, url] of Object.entries(avatarUrls)) {
    const id = Number(rawId)
    if (expectedIds.has(id)) continue
    URL.revokeObjectURL(url)
    delete avatarUrls[id]
  }
  for (const agent of agents) {
    if (!agent.has_avatar || avatarUrls[agent.agent_id] || loadingAvatarIds.has(agent.agent_id)) continue
    loadingAvatarIds.add(agent.agent_id)
    try {
      const url = await agentService.getAvatarBlobUrl(agent.agent_id)
      if (disposed || !agents.some(item => item.agent_id === agent.agent_id && item.has_avatar)) {
        URL.revokeObjectURL(url)
      } else {
        avatarUrls[agent.agent_id] = url
      }
    } catch (error) {
      console.error(`Failed to load dashboard avatar for agent ${agent.agent_id}:`, error)
    } finally {
      loadingAvatarIds.delete(agent.agent_id)
    }
  }
}

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]?.toUpperCase()).join('')
}

function formatCompact(value: number): string {
  return Intl.NumberFormat(locale.value, { notation: 'compact', maximumFractionDigits: 1 }).format(value)
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

function formatPercent(value: number): string {
  return `${value.toLocaleString(locale.value, { maximumFractionDigits: 1 })} %`
}

function formatDuration(value: number): string {
  return value < 1
    ? `${Math.round(value * 1000)} ms`
    : `${value.toLocaleString(locale.value, { maximumFractionDigits: 1 })} s`
}

function successColor(value: number): string {
  if (value >= 90) return 'positive'
  if (value >= 70) return 'warning'
  return 'negative'
}
</script>

<style scoped>
.agent-table { background: transparent; }
.agent-table :deep(.q-table thead tr) { background: #f6f8fc; }
.agent-table :deep(.q-table th) { height: 46px; color: #778299; font-size: 0.72rem; font-weight: 750; letter-spacing: 0.045em; text-transform: uppercase; }
.agent-table :deep(.q-table tbody td) { height: 62px; color: #36415a; border-color: #edf0f5; }
.agent-table :deep(.q-table tbody tr:hover) { background: #f9fbff; }

body.body--dark .agent-table :deep(.q-table thead tr) { background: #20242e; }
body.body--dark .agent-table :deep(.q-table tbody td) { color: #c4cddd; border-color: #2e3238; }
body.body--dark .agent-table :deep(.q-table tbody tr:hover) { background: #232a3d; }
body.body--dark .agent-avatar { color: #9ab2f0; background: linear-gradient(145deg, #24304d, #1e2740); }
body.body--dark .agent-name { color: #dbe2ee; }
body.body--dark .success-cell { color: #aab4c9; }

.agent-cell { display: flex; min-width: 185px; gap: 11px; align-items: center; }
.agent-avatar { color: #3f69d8; background: linear-gradient(145deg, #e7edff, #f3f6ff); font-size: 0.78rem; font-weight: 750; }
.agent-avatar :deep(img) { width: 100%; height: 100%; object-fit: cover; }
.agent-identity { display: flex; min-width: 0; flex-direction: column; }
.agent-name { overflow: hidden; color: #22304d; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.agent-title { max-width: 190px; overflow: hidden; color: #9099aa; font-size: 0.74rem; text-overflow: ellipsis; white-space: nowrap; }
.success-cell { display: inline-grid; width: 78px; gap: 5px; color: #4d5972; font-variant-numeric: tabular-nums; }
.number-cell { font-variant-numeric: tabular-nums; }
.incident-badge { min-width: 28px; justify-content: center; font-variant-numeric: tabular-nums; }
</style>
