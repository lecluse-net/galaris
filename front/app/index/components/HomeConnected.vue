<template>
  <q-page class="dashboard-page q-pa-md">
    <div class="dashboard-shell">
      <PageHeader :icon="navigationIcon('dashboard')"
        v-if="canSeeDashboard"
        :title="t('nav.dashboard')"
        :description="t('nav.dashboard_desc')"
      >
        <!--
          UX INVARIANT — character anchoring:
          Keep the current-month selector immediately after the page title.
          Never move this block to the right-aligned #actions slot.
        -->
        <template #title-after>
          <div class="dashboard-controls">
            <q-select
              :model-value="dashboardStore.selectedMonth"
              :options="monthOptions"
              emit-value
              map-options
              dense
              outlined
              options-dense
              :label="t('index.dashboard.month')"
              class="month-select"
              popup-content-class="dashboard-month-menu"
              @update:model-value="onMonthChange"
            >
              <template #prepend><q-icon name="calendar_month" /></template>
            </q-select>
            <q-btn
              round
              flat
              color="primary"
              icon="refresh"
              :loading="dashboardStore.loading"
              :aria-label="t('index.dashboard.refresh')"
              @click="refreshDashboard"
            >
              <q-tooltip>{{ t('index.dashboard.refresh') }}</q-tooltip>
            </q-btn>
          </div>
        </template>
      </PageHeader>

      <q-banner
        v-if="canSeeDashboard && dashboardStore.error"
        rounded
        class="bg-red-1 text-negative q-mb-lg"
      >
        <template #avatar><q-icon name="error_outline" /></template>
        {{ t('index.dashboard.loadError') }}
        <template #action>
          <q-btn flat color="negative" :label="t('index.dashboard.retry')" @click="refreshDashboard" />
        </template>
      </q-banner>

      <template v-if="privilegeStore.loaded && !canSeeDashboard">
        <section class="welcome-card" aria-labelledby="galaris-welcome-title">
          <div class="welcome-card__mark" aria-hidden="true">
            <q-icon name="hub" />
          </div>
          <p class="welcome-card__eyebrow">
            {{ t('index.dashboard.welcome.eyebrow') }}
          </p>
          <h1 id="galaris-welcome-title">
            {{ t('index.dashboard.welcome.title') }}
          </h1>
          <p class="welcome-card__intro">
            {{ t('index.dashboard.welcome.intro') }}
          </p>
          <q-separator class="welcome-card__separator" />
          <p class="welcome-card__detail">
            {{ t('index.dashboard.welcome.detail') }}
          </p>
        </section>
      </template>

      <template v-else-if="canSeeDashboard && dashboardStore.data">
        <div class="row q-col-gutter-lg q-mb-lg">
          <div class="col-12 col-sm-6 col-xl-3">
            <DashboardMetricCard
              :label="t('index.dashboard.monthlyCost')"
              :value="formatCurrency(totals.cost)"
              icon="payments"
              tone="amber"
              :trend="trend(totals.cost, previousTotals.cost)"
              :hint="t('index.dashboard.vsPrevious')"
              :detail="apiCostDetail(totals.cost, totals.inference_cost)"
              inverse-trend
            />
          </div>
          <div class="col-12 col-sm-6 col-xl-3">
            <DashboardMetricCard
              :label="t('index.dashboard.consumedTokens')"
              :value="formatCompact(totals.tokens)"
              icon="data_usage"
              tone="violet"
              :trend="trend(totals.tokens, previousTotals.tokens)"
              :hint="t('index.dashboard.vsPrevious')"
            />
          </div>
          <div class="col-12 col-sm-6 col-xl-3">
            <DashboardMetricCard
              :label="t('index.dashboard.llmCalls')"
              :value="formatInteger(totals.llm_calls)"
              icon="hub"
              tone="blue"
              :trend="trend(totals.llm_calls, previousTotals.llm_calls)"
              :hint="t('index.dashboard.vsPrevious')"
            />
          </div>
          <div class="col-12 col-sm-6 col-xl-3">
            <DashboardMetricCard
              :label="t('index.dashboard.tasksHandled')"
              :value="formatInteger(totals.tasks)"
              icon="task_alt"
              tone="teal"
              :trend="trend(totals.tasks, previousTotals.tasks)"
              :hint="t('index.dashboard.vsPrevious')"
            />
          </div>
        </div>

        <DashboardLiveActivity class="q-mb-lg" />

        <q-card flat class="dashboard-card q-mb-lg">
          <DashboardSectionHeader
            compact
            icon="bar_chart"
            tone="blue"
            :title="chartTitle"
            :subtitle="t('index.dashboard.usageSubtitle')"
          >
            <template #action>
                <q-btn-toggle
                  v-model="selectedMetric"
                  no-caps
                  unelevated
                  rounded
                  toggle-color="primary"
                  color="grey-2"
                  text-color="grey-8"
                  :options="metricOptions"
                  class="metric-toggle"
                />
            </template>
          </DashboardSectionHeader>
          <q-separator />
          <q-card-section class="usage-card-body">
            <DashboardUsageChart
              :month="dashboardStore.data.month"
              :points="dashboardStore.data.daily_usage"
              :metric="selectedMetric"
            />
          </q-card-section>
        </q-card>

        <div class="row q-col-gutter-lg q-mb-lg items-stretch">
          <div class="col-12 col-lg-8">
            <q-card flat class="dashboard-card full-height">
              <DashboardSectionHeader
                compact
                icon="donut_small"
                tone="violet"
                :title="t('index.dashboard.modelBreakdown')"
                :subtitle="modelBreakdownSubtitle"
              >
                <template #badge>
                  <q-badge rounded class="section-count-badge">
                    {{ t('index.dashboard.modelCount', { count: activeModelCount }) }}
                  </q-badge>
                </template>
              </DashboardSectionHeader>
              <q-separator />
              <q-card-section class="model-breakdown">
                <template v-if="modelBreakdown.length">
                  <div class="model-summary">
                    <div class="model-summary__totals">
                      <div>
                        <span>{{ t('index.dashboard.tokens') }}</span>
                        <strong>{{ formatCompact(modelTotalTokens) }}</strong>
                      </div>
                      <q-separator vertical />
                      <div>
                        <span>{{ t('index.dashboard.cost') }}</span>
                        <strong>{{ formatCurrency(modelTotalCost) }}</strong>
                        <small v-if="hasDistinctApiCost(modelTotalCost, modelTotalInferenceCost)">
                          {{ t('index.dashboard.apiEquivalent', { cost: formatCurrency(modelTotalInferenceCost) }) }}
                        </small>
                      </div>
                    </div>
                    <div class="model-summary__context">
                      <q-icon name="insights" size="18px" />
                      {{ t('index.dashboard.modelsUsed', { count: activeModelCount }) }}
                    </div>
                  </div>

                  <div class="model-chart-layout">
                    <DashboardModelPieChart
                      v-model:active-key="activeModelKey"
                      :slices="modelBreakdown"
                      :ariaLabel="t('index.dashboard.modelChartAria')"
                    />

                    <div class="model-legend">
                      <article
                        v-for="model in modelBreakdown"
                        :key="model.key"
                        class="model-legend__row"
                        :class="{
                          'model-legend__row--active': activeModelKey === model.key,
                          'model-legend__row--muted': activeModelKey !== null && activeModelKey !== model.key,
                        }"
                        tabindex="0"
                        @mouseenter="activeModelKey = model.key"
                        @mouseleave="activeModelKey = null"
                        @focus="activeModelKey = model.key"
                        @blur="activeModelKey = null"
                      >
                        <span class="model-legend__dot" :style="{ background: model.color }"></span>
                        <div class="model-legend__identity">
                          <strong>{{ model.label }}</strong>
                          <span>{{ model.provider || t('index.dashboard.unknownProvider') }}</span>
                        </div>
                        <div class="model-legend__metrics">
                          <strong>{{ formatPercent(model.share * 100) }}</strong>
                          <div>
                            <span>{{ formatCompact(model.tokens) }}</span>
                            <span>{{ formatCurrency(model.cost) }}</span>
                            <small v-if="hasDistinctApiCost(model.cost, model.inferenceCost)">
                              {{ t('index.dashboard.apiEquivalentShort', { cost: formatCurrency(model.inferenceCost) }) }}
                            </small>
                          </div>
                        </div>
                        <div class="model-legend__calls">
                          {{ formatInteger(model.calls) }} {{ t('index.dashboard.callsShort') }}
                          <template v-if="model.errors">
                            · {{ t('index.dashboard.modelErrors', { count: formatInteger(model.errors) }) }}
                          </template>
                        </div>
                      </article>
                    </div>
                  </div>
                </template>
                <div v-else class="compact-empty model-breakdown__empty">
                  <q-icon name="donut_large" size="36px" />
                  {{ t('index.dashboard.noUsage') }}
                </div>
              </q-card-section>
            </q-card>
          </div>

          <div class="col-12 col-lg-4">
            <q-card flat class="dashboard-card full-height">
              <DashboardSectionHeader
                compact
                icon="health_and_safety"
                tone="teal"
                :title="t('index.dashboard.reliability')"
                :subtitle="t('index.dashboard.reliabilitySubtitle')"
              />
              <q-separator />
              <q-card-section class="health-body">
                <div class="health-gauges">
                  <div class="health-gauge">
                    <q-circular-progress
                      show-value
                      :value="totals.task_success_rate"
                      size="96px"
                      :thickness="0.12"
                      color="positive"
                      track-color="grey-3"
                    >
                      <strong>{{ formatPercent(totals.task_success_rate) }}</strong>
                    </q-circular-progress>
                    <span>{{ t('index.dashboard.taskSuccess') }}</span>
                  </div>
                  <div class="health-gauge">
                    <q-circular-progress
                      show-value
                      :value="totals.llm_success_rate"
                      size="96px"
                      :thickness="0.12"
                      color="primary"
                      track-color="grey-3"
                    >
                      <strong>{{ formatPercent(totals.llm_success_rate) }}</strong>
                    </q-circular-progress>
                    <span>{{ t('index.dashboard.llmSuccess') }}</span>
                  </div>
                </div>

                <div class="health-stat-grid">
                  <div class="health-stat health-stat--blue">
                    <q-icon name="speed" />
                    <span>{{ t('index.dashboard.avgLatency') }}</span>
                    <strong>{{ formatDuration(totals.average_llm_duration) }}</strong>
                  </div>
                  <div class="health-stat" :class="totals.incidents ? 'health-stat--red' : 'health-stat--green'">
                    <q-icon :name="totals.incidents ? 'warning_amber' : 'check_circle'" />
                    <span>{{ t('index.dashboard.incidents') }}</span>
                    <strong>{{ formatInteger(totals.incidents) }}</strong>
                  </div>
                  <div class="health-stat health-stat--neutral">
                    <q-icon name="task_alt" />
                    <span>{{ t('index.dashboard.taskErrors') }}</span>
                    <strong>{{ formatInteger(totals.task_errors) }}</strong>
                  </div>
                  <div class="health-stat health-stat--neutral">
                    <q-icon name="memory" />
                    <span>{{ t('index.dashboard.llmErrors') }}</span>
                    <strong>{{ formatInteger(totals.llm_errors) }}</strong>
                  </div>
                </div>
              </q-card-section>
            </q-card>
          </div>
        </div>

        <q-card flat class="dashboard-card agent-performance-card">
          <DashboardSectionHeader
            compact
            icon="groups"
            tone="blue"
            :title="t('index.dashboard.agentPerformance')"
            :subtitle="t('index.dashboard.agentPerformanceSubtitle')"
          >
            <template #badge>
              <q-badge rounded class="section-count-badge">
                {{ t('index.dashboard.agentCount', { count: dashboardStore.data.agents.length }) }}
              </q-badge>
            </template>
            <template #action>
              <q-btn v-if="canViewAgents" flat no-caps color="primary" icon-right="arrow_forward" :label="t('index.dashboard.manageAgents')" to="/agent" />
            </template>
          </DashboardSectionHeader>
          <q-separator />
          <DashboardAgentTable :agents="dashboardStore.data.agents" />
        </q-card>

        <q-inner-loading :showing="dashboardStore.loading" color="primary" />
      </template>

      <div v-else class="dashboard-loading">
        <div class="row q-col-gutter-lg">
          <div v-for="index in 4" :key="index" class="col-12 col-sm-6 col-xl-3">
            <q-skeleton type="rect" height="132px" class="dashboard-skeleton" />
          </div>
        </div>
        <q-skeleton type="rect" height="430px" class="dashboard-skeleton q-mt-lg" />
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { PageHeader } from '@/core/util'
import { useDashboardStore } from '../stores/dashboardStore'
import DashboardMetricCard from './DashboardMetricCard.vue'
import DashboardUsageChart from './DashboardUsageChart.vue'
import DashboardAgentTable from './DashboardAgentTable.vue'
import DashboardModelPieChart from './DashboardModelPieChart.vue'
import DashboardSectionHeader from './DashboardSectionHeader.vue'
import DashboardLiveActivity from './DashboardLiveActivity.vue'

type Metric = 'tokens' | 'cost'

interface ModelBreakdown {
  key: string
  label: string
  provider: string
  calls: number
  errors: number
  tokens: number
  cost: number
  inferenceCost: number
  value: number
  share: number
  color: string
}

interface RankedModel {
  key: string
  label: string
  provider: string
  calls: number
  errors: number
  tokens: number
  cost: number
  inferenceCost: number
  value: number
}

const { t, locale } = useI18n()
const privilegeStore = usePrivilegeStore()
const dashboardStore = useDashboardStore()
const selectedMetric = ref<Metric>('tokens')
const activeModelKey = ref<string | null>(null)

const canSeeDashboard = computed(() => (
  privilegeStore.hasPrivilege(privileges.TASK_ACCESS)
  || privilegeStore.hasPrivilege(privileges.TASK_EDIT)
))
const canViewAgents = computed(() => (
  privilegeStore.hasPrivilege(privileges.AGENT_ACCESS)
  || privilegeStore.hasPrivilege(privileges.AGENT_EDIT)
))

const totals = computed(() => dashboardStore.data!.totals)
const previousTotals = computed(() => dashboardStore.data!.previous_totals)

const monthOptions = computed(() => {
  const months = dashboardStore.availableMonths.length
    ? dashboardStore.availableMonths
    : [dashboardStore.selectedMonth]
  return months.map(month => ({ value: month, label: formatMonth(month) }))
})

const metricOptions = computed(() => [
  { label: t('index.dashboard.tokens'), value: 'tokens' },
  { label: t('index.dashboard.dollars'), value: 'cost' },
])

const chartTitle = computed(() => (
  selectedMetric.value === 'tokens'
    ? t('index.dashboard.dailyTokens')
    : t('index.dashboard.dailyCost')
))

const modelBreakdownSubtitle = computed(() => (
  selectedMetric.value === 'tokens'
    ? t('index.dashboard.shareOfTokens')
    : t('index.dashboard.shareOfCost')
))

const breakdownPalette = [
  '#4f7cff',
  '#8b5cf6',
  '#10a78e',
  '#f09a32',
  '#e45168',
  '#27a6d8',
]

const rankedModels = computed<RankedModel[]>(() => {
  const models = new Map<string, {
    label: string
    provider: string
    calls: number
    errors: number
    tokens: number
    cost: number
    inferenceCost: number
  }>()
  for (const point of dashboardStore.data?.daily_usage ?? []) {
    const current = models.get(point.llm_key)
    models.set(point.llm_key, {
      label: point.llm_label,
      provider: point.provider_name,
      calls: (current?.calls ?? 0) + point.calls,
      errors: (current?.errors ?? 0) + point.errors,
      tokens: (current?.tokens ?? 0) + point.tokens,
      cost: (current?.cost ?? 0) + point.cost,
      inferenceCost: (current?.inferenceCost ?? 0) + point.inference_cost,
    })
  }
  return [...models.entries()]
    .map(([key, model]) => ({ key, ...model, value: model[selectedMetric.value] }))
    .sort((a, b) => b.value - a.value)
})

const activeModelCount = computed(() => rankedModels.value.length)
const modelTotalValue = computed(() => rankedModels.value.reduce((sum, model) => sum + model.value, 0))
const modelTotalTokens = computed(() => rankedModels.value.reduce((sum, model) => sum + model.tokens, 0))
const modelTotalCost = computed(() => rankedModels.value.reduce((sum, model) => sum + model.cost, 0))
const modelTotalInferenceCost = computed(() => (
  rankedModels.value.reduce((sum, model) => sum + model.inferenceCost, 0)
))

const modelBreakdown = computed<ModelBreakdown[]>(() => {
  const ranked = rankedModels.value
  const visibleModels: RankedModel[] = ranked.length <= 6
    ? ranked
    : [
        ...ranked.slice(0, 5),
        ranked.slice(5).reduce<RankedModel>((aggregate, model) => ({
          ...aggregate,
          calls: aggregate.calls + model.calls,
          errors: aggregate.errors + model.errors,
          tokens: aggregate.tokens + model.tokens,
          cost: aggregate.cost + model.cost,
          inferenceCost: aggregate.inferenceCost + model.inferenceCost,
          value: aggregate.value + model.value,
        }), {
          key: '__other__',
          label: t('index.dashboard.otherModels'),
          provider: t('index.dashboard.multipleProviders'),
          calls: 0,
          errors: 0,
          tokens: 0,
          cost: 0,
          inferenceCost: 0,
          value: 0,
        }),
      ]

  return visibleModels.map((model, index) => ({
    ...model,
    share: modelTotalValue.value ? model.value / modelTotalValue.value : 0,
    color: breakdownPalette[index % breakdownPalette.length] ?? '#4f7cff',
  }))
})

function trend(current: number, previous: number): number | null {
  if (previous === 0) return current === 0 ? 0 : null
  return ((current - previous) / previous) * 100
}

function formatMonth(month: string): string {
  const [year = 0, monthNumber = 1] = month.split('-').map(Number)
  return new Intl.DateTimeFormat(locale.value, { month: 'long', year: 'numeric', timeZone: 'UTC' })
    .format(new Date(Date.UTC(year, monthNumber - 1, 1)))
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

function hasDistinctApiCost(billedCost: number, apiCost: number): boolean {
  return formatCurrency(billedCost) !== formatCurrency(apiCost)
}

function apiCostDetail(billedCost: number, apiCost: number): string | undefined {
  if (!hasDistinctApiCost(billedCost, apiCost)) return undefined
  return t('index.dashboard.apiEquivalent', { cost: formatCurrency(apiCost) })
}

function formatInteger(value: number): string {
  return Intl.NumberFormat(locale.value, { maximumFractionDigits: 0 }).format(value)
}

function formatCompact(value: number): string {
  return Intl.NumberFormat(locale.value, { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function formatPercent(value: number): string {
  return `${value.toLocaleString(locale.value, { maximumFractionDigits: 1 })} %`
}

function formatDuration(value: number): string {
  return value < 1
    ? `${Math.round(value * 1000)} ms`
    : `${value.toLocaleString(locale.value, { maximumFractionDigits: 1 })} s`
}

function onMonthChange(month: string | null): void {
  if (month) void dashboardStore.selectMonth(month)
}

function refreshDashboard(): void {
  void dashboardStore.fetchDashboard()
}

watch(canSeeDashboard, (allowed) => {
  if (allowed) void dashboardStore.selectMonth(dashboardStore.selectedMonth)
}, { immediate: true })
</script>

<style scoped>
.dashboard-page {
  min-height: 100vh;
  background: transparent;
}

.dashboard-shell { position: relative; width: 100%; }
.dashboard-controls { display: flex; flex: 0 0 auto; gap: 8px; align-items: center; }
.month-select { width: 210px; }
.month-select :deep(.q-field__control) { border-radius: 10px; }

.dashboard-card { overflow: hidden; border: 1px solid rgba(35, 50, 84, 0.085); border-radius: 19px; background: rgba(255, 255, 255, 0.97); box-shadow: 0 10px 34px rgba(31, 45, 75, 0.065); }
.usage-card-body { min-height: 385px; padding: 16px 22px 8px; }
.metric-toggle { border: 1px solid #e2e6ee; }
.section-count-badge { padding: 4px 8px; color: #5b6c90; background: #eef2fa; font-size: 0.66rem; font-weight: 750; }

.model-breakdown { display: flex; min-height: 430px; flex-direction: column; padding: 20px 22px 22px; }
.model-summary { display: flex; gap: 16px; align-items: center; justify-content: space-between; margin-bottom: 16px; padding: 14px 16px; border: 1px solid #e8ecf5; border-radius: 13px; background: linear-gradient(105deg, #f7f9ff, #fbfaff); }
.model-summary__totals { display: flex; gap: 18px; align-items: stretch; }
.model-summary__totals > div { display: flex; min-width: 95px; flex-direction: column; }
.model-summary span { color: #7d88a0; font-size: 0.7rem; font-weight: 650; }
.model-summary strong { margin-top: 2px; color: #273650; font-size: 1.25rem; font-weight: 800; font-variant-numeric: tabular-nums; }
.model-summary small { margin-top: 3px; color: #97640e; font-size: 0.64rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.model-summary__context { display: flex; gap: 7px; align-items: center; color: #7251c3; font-size: 0.73rem; font-weight: 700; }

.model-chart-layout { display: grid; grid-template-columns: minmax(230px, 0.8fr) minmax(300px, 1.2fr); gap: clamp(20px, 4vw, 48px); align-items: center; }
.model-legend { display: grid; gap: 7px; }
.model-legend__row { display: grid; grid-template-columns: 10px minmax(0, 1fr) auto; gap: 2px 10px; align-items: center; padding: 10px 12px; border: 1px solid #eaedf4; border-radius: 11px; outline: none; background: #fff; transition: opacity 160ms ease, border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease; }
.model-legend__row--active { border-color: #c9d4ee; box-shadow: 0 8px 20px rgba(42, 57, 91, 0.11); transform: translateX(4px); }
.model-legend__row--muted { opacity: 0.48; }
.model-legend__row:focus-visible { outline: 2px solid #5278d9; outline-offset: 2px; }
.model-legend__dot { grid-row: 1 / 3; width: 10px; height: 10px; border-radius: 50%; box-shadow: 0 0 0 4px color-mix(in srgb, currentColor 8%, transparent); }
.model-legend__identity { display: flex; min-width: 0; flex-direction: column; }
.model-legend__identity strong { overflow: hidden; color: #2d3a54; font-size: 0.78rem; font-weight: 760; text-overflow: ellipsis; white-space: nowrap; }
.model-legend__identity span { overflow: hidden; color: #9aa3b4; font-size: 0.64rem; text-overflow: ellipsis; white-space: nowrap; }
.model-legend__metrics { display: flex; gap: 12px; align-items: center; justify-content: flex-end; font-variant-numeric: tabular-nums; }
.model-legend__metrics strong { color: #34425d; font-size: 0.9rem; font-weight: 800; }
.model-legend__metrics > div { display: flex; min-width: 92px; flex-direction: column; align-items: flex-end; }
.model-legend__metrics span { color: #6f7a90; font-size: 0.8rem; font-weight: 700; text-align: right; }
.model-legend__metrics span + span { margin-top: 1px; color: #97640e; }
.model-legend__metrics small { margin-top: 2px; color: #7d65b5; font-size: 0.72rem; font-weight: 700; text-align: right; }
.model-legend__calls { grid-column: 2 / 4; color: #929bad; font-size: 0.63rem; }
.compact-empty { display: flex; flex: 1; flex-direction: column; gap: 8px; align-items: center; justify-content: center; color: #a1a9b8; }
.model-breakdown__empty { min-height: 350px; }

.health-body { min-height: 430px; padding: 24px 20px 22px; }
.health-gauges { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.health-gauge { display: flex; min-width: 0; flex-direction: column; gap: 10px; align-items: center; padding: 17px 8px 15px; border: 1px solid #e9edf3; border-radius: 14px; background: #fbfcfe; text-align: center; }
.health-gauge :deep(.q-circular-progress__text) { color: #293852; font-size: 0.78rem; font-variant-numeric: tabular-nums; }
.health-gauge > span { min-height: 32px; color: #6f7b92; font-size: 0.72rem; font-weight: 700; line-height: 1.35; }
.health-stat-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.health-stat { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 2px 8px; align-items: center; padding: 12px; color: var(--health-color); border-radius: 12px; background: var(--health-background); }
.health-stat .q-icon { grid-row: 1 / 3; font-size: 20px; }
.health-stat span { overflow: hidden; color: #7d8799; font-size: 0.66rem; text-overflow: ellipsis; white-space: nowrap; }
.health-stat strong { color: #31405a; font-size: 0.84rem; font-weight: 800; font-variant-numeric: tabular-nums; }
.health-stat--blue { --health-color: #4c75d8; --health-background: #f0f4ff; }
.health-stat--green { --health-color: #07977f; --health-background: #ecf8f5; }
.health-stat--red { --health-color: #d84c63; --health-background: #fff0f2; }
.health-stat--neutral { --health-color: #78849b; --health-background: #f5f6f9; }

.agent-performance-card { margin-bottom: 12px; }
.welcome-card { width: min(680px, 100%); margin: clamp(56px, 12vh, 120px) auto 0; padding: clamp(34px, 6vw, 56px); color: #526078; border: 1px solid #e2e7f0; border-radius: 22px; background: rgba(255, 255, 255, 0.82); text-align: center; }
.welcome-card__mark { display: inline-grid; width: 54px; height: 54px; place-items: center; color: #4f70c8; border-radius: 16px; background: #edf2ff; }
.welcome-card__mark .q-icon { font-size: 28px; }
.welcome-card__eyebrow { margin: 20px 0 5px; color: #70809d; font-size: 0.72rem; font-weight: 750; letter-spacing: 0.14em; text-transform: uppercase; }
.welcome-card h1 { margin: 0; color: #273650; font-size: clamp(2.1rem, 6vw, 3.2rem); font-weight: 780; letter-spacing: -0.04em; }
.welcome-card__intro { max-width: 560px; margin: 18px auto 0; color: #4f5f78; font-size: 1.04rem; line-height: 1.7; }
.welcome-card__separator { width: 72px; margin: 26px auto; }
.welcome-card__detail { max-width: 540px; margin: 0 auto; color: #78859a; line-height: 1.65; }
.dashboard-skeleton { overflow: hidden; border-radius: 18px; }

body.body--dark .setup-banner { color: #b9c8e8; border-color: #33415e; background: #1c2333; }
body.body--dark .dashboard-card { border-color: rgba(255, 255, 255, 0.09); background: rgba(29, 29, 29, 0.97); box-shadow: 0 10px 34px rgba(0, 0, 0, 0.35); }
body.body--dark .metric-toggle { border-color: #3a3f47; }
body.body--dark .section-count-badge { color: #a8b6d4; background: #262d3d; }
body.body--dark .model-summary { border-color: #33384a; background: linear-gradient(105deg, #20242f, #232130); }
body.body--dark .model-summary strong { color: #dbe2ee; }
body.body--dark .model-summary small { color: #d9a54a; }
body.body--dark .model-summary__context { color: #a68ce8; }
body.body--dark .model-legend__row { border-color: #33384a; background: #1d1d1d; }
body.body--dark .model-legend__row--active { border-color: #4a5877; box-shadow: 0 8px 20px rgba(0, 0, 0, 0.4); }
body.body--dark .model-legend__identity strong { color: #dbe2ee; }
body.body--dark .model-legend__metrics strong { color: #cfd8e8; }
body.body--dark .model-legend__metrics span { color: #9aa6bd; }
body.body--dark .health-gauge > span { color: #9aa6bd; }
body.body--dark .model-legend__metrics span + span { color: #d9a54a; }
body.body--dark .model-legend__metrics small { color: #b9a4e8; }
body.body--dark .health-gauge { border-color: #33384a; background: #20242e; }
body.body--dark .health-gauge :deep(.q-circular-progress__text) { color: #dbe2ee; }
body.body--dark .health-stat strong { color: #dbe2ee; }
body.body--dark .health-stat--blue { --health-background: #1e2740; }
body.body--dark .health-stat--green { --health-background: #17302b; }
body.body--dark .health-stat--red { --health-background: #38222a; }
body.body--dark .health-stat--neutral { --health-background: #262a33; }
body.body--dark .welcome-card { color: #aab5c8; border-color: #353b48; background: rgba(30, 31, 35, 0.82); }
body.body--dark .welcome-card__mark { color: #9bb3f0; background: #252d40; }
body.body--dark .welcome-card__eyebrow { color: #8f9bb1; }
body.body--dark .welcome-card h1 { color: #e3e8f1; }
body.body--dark .welcome-card__intro { color: #bac4d5; }
body.body--dark .welcome-card__detail { color: #919daf; }

@media (max-width: 1023.98px) {
  .month-select { width: min(280px, calc(100% - 52px)); }
}

@media (max-width: 599px) {
  .dashboard-controls { width: 100%; margin-bottom: 12px; }
  .metric-toggle { align-self: stretch; }
  .metric-toggle :deep(.q-btn) { flex: 1; }
  .usage-card-body { padding-inline: 12px; }
  .model-chart-layout { grid-template-columns: 1fr; }
  .model-summary { align-items: flex-start; flex-direction: column; }
  .model-summary__totals { width: 100%; }
  .health-gauge :deep(.q-circular-progress) { font-size: 0.75rem; }
  .health-stat-grid { grid-template-columns: 1fr; }
}
</style>
