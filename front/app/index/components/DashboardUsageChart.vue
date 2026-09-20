<template>
  <div class="usage-chart">
    <div class="usage-chart__legend">
      <div v-for="item in series" :key="item.key" class="usage-chart__legend-item">
        <span class="usage-chart__dot" :style="{ backgroundColor: item.color }"></span>
        <span class="usage-chart__legend-label">{{ item.label }}</span>
        <span v-if="item.provider" class="usage-chart__provider">{{ item.provider }}</span>
      </div>
    </div>

    <div class="usage-chart__canvas">
      <svg
        :viewBox="`0 0 ${chartWidth} ${chartHeight}`"
        role="img"
        :aria-label="t('index.dashboard.usageChartAria')"
      >
        <g v-for="line in gridLines" :key="line.value">
          <line
            :x1="margin.left"
            :x2="chartWidth - margin.right"
            :y1="line.y"
            :y2="line.y"
            class="usage-chart__grid"
          />
          <text :x="margin.left - 12" :y="line.y + 4" text-anchor="end" class="usage-chart__axis-label">
            {{ formatAxis(line.value) }}
          </text>
        </g>

        <g v-for="bar in bars" :key="bar.date">
          <rect
            v-for="segment in bar.segments"
            :key="segment.key"
            :x="segment.x"
            :y="segment.y"
            :width="segment.width"
            :height="segment.height"
            :fill="segment.color"
            rx="2"
            class="usage-chart__bar"
          >
            <title>{{ segment.tooltip }}</title>
          </rect>
          <text
            v-if="bar.showLabel"
            :x="bar.x + barWidth / 2"
            :y="chartHeight - 10"
            text-anchor="middle"
            class="usage-chart__axis-label usage-chart__day-label"
          >
            {{ bar.label }}
          </text>
        </g>
      </svg>

      <div v-if="!hasUsage" class="usage-chart__empty">
        <q-icon name="monitoring" size="40px" />
        <span>{{ t('index.dashboard.noUsage') }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DailyLlmUsage } from '../services/dashboardService'

type Metric = 'tokens' | 'cost'

interface SeriesItem {
  key: string
  label: string
  provider: string
  color: string
  total: number
}

interface DayValue {
  date: string
  label: string
  values: Map<string, number>
  total: number
}

const props = defineProps<{
  month: string
  points: DailyLlmUsage[]
  metric: Metric
}>()

const { t, locale } = useI18n()
const chartWidth = 1000
const chartHeight = 330
const margin = { top: 14, right: 18, bottom: 38, left: 76 }
const plotHeight = chartHeight - margin.top - margin.bottom
const plotWidth = chartWidth - margin.left - margin.right
const palette = ['#4f7cff', '#8b5cf6', '#10a78e', '#f09a32', '#e45168', '#27a6d8', '#6a7b98', '#c05bc8']

const metricValue = (point: DailyLlmUsage): number => (
  props.metric === 'tokens' ? point.tokens : point.cost
)

const rankedSeries = computed(() => {
  const entries = new Map<string, Omit<SeriesItem, 'color'>>()
  for (const point of props.points) {
    const current = entries.get(point.llm_key)
    entries.set(point.llm_key, {
      key: point.llm_key,
      label: point.llm_label,
      provider: point.provider_name,
      total: (current?.total ?? 0) + metricValue(point),
    })
  }
  return [...entries.values()].sort((a, b) => b.total - a.total)
})

const visibleKeys = computed(() => new Set(rankedSeries.value.slice(0, 7).map(item => item.key)))

const series = computed<SeriesItem[]>(() => {
  const visible = rankedSeries.value.slice(0, 7).map((item, index) => ({
    ...item,
    color: palette[index % palette.length],
  }))
  if (rankedSeries.value.length > 7) {
    visible.push({
      key: '__other__',
      label: t('index.dashboard.otherModels'),
      provider: '',
      total: rankedSeries.value.slice(7).reduce((sum, item) => sum + item.total, 0),
      color: palette[7],
    })
  }
  return visible
})

const daysInMonth = computed(() => {
  const [year, monthNumber] = props.month.split('-').map(Number)
  return new Date(Date.UTC(year, monthNumber, 0)).getUTCDate()
})

const dayValues = computed<DayValue[]>(() => {
  const pointsByDay = new Map<string, DailyLlmUsage[]>()
  for (const point of props.points) {
    const items = pointsByDay.get(point.date) ?? []
    items.push(point)
    pointsByDay.set(point.date, items)
  }

  return Array.from({ length: daysInMonth.value }, (_, index) => {
    const day = index + 1
    const date = `${props.month}-${String(day).padStart(2, '0')}`
    const values = new Map<string, number>()
    for (const point of pointsByDay.get(date) ?? []) {
      const key = visibleKeys.value.has(point.llm_key) ? point.llm_key : '__other__'
      values.set(key, (values.get(key) ?? 0) + metricValue(point))
    }
    const total = [...values.values()].reduce((sum, value) => sum + value, 0)
    return { date, label: String(day).padStart(2, '0'), values, total }
  })
})

const hasUsage = computed(() => dayValues.value.some(day => day.total > 0))

function niceMaximum(value: number): number {
  if (value <= 0) return 1
  const targetIntervals = 4
  const roughStep = value / targetIntervals
  const magnitude = 10 ** Math.floor(Math.log10(roughStep))
  const normalizedStep = roughStep / magnitude
  const steps = [1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 7.5, 10]
  const step = (steps.find(candidate => candidate >= normalizedStep) ?? 10) * magnitude
  return Math.ceil(value / step) * step
}

const maximum = computed(() => niceMaximum(Math.max(...dayValues.value.map(day => day.total), 0)))
const dayWidth = computed(() => plotWidth / Math.max(daysInMonth.value, 1))
const barWidth = computed(() => Math.max(5, dayWidth.value * 0.66))
const labelStep = computed(() => Math.max(1, Math.ceil(daysInMonth.value / 9)))

const gridLines = computed(() => Array.from({ length: 5 }, (_, index) => {
  const value = maximum.value * (index / 4)
  return {
    value,
    y: margin.top + plotHeight - (value / maximum.value) * plotHeight,
  }
}))

const bars = computed(() => dayValues.value.map((day, dayIndex) => {
  const x = margin.left + dayIndex * dayWidth.value + (dayWidth.value - barWidth.value) / 2
  let cumulative = 0
  const segments = series.value.map(item => {
    const value = day.values.get(item.key) ?? 0
    const height = value > 0 ? Math.max(1.5, (value / maximum.value) * plotHeight) : 0
    cumulative += height
    return {
      key: item.key,
      x,
      y: margin.top + plotHeight - cumulative,
      width: barWidth.value,
      height,
      color: item.color,
      tooltip: `${formatDate(day.date)} · ${item.label}: ${formatMetric(value)}`,
    }
  })
  return {
    date: day.date,
    label: day.label,
    x,
    segments,
    showLabel: dayIndex === 0 || dayIndex === daysInMonth.value - 1 || dayIndex % labelStep.value === 0,
  }
}))

function formatMetric(value: number): string {
  if (props.metric === 'cost') {
    return new Intl.NumberFormat(locale.value, {
      style: 'currency',
      currency: 'USD',
      currencyDisplay: 'narrowSymbol',
      minimumFractionDigits: value < 0.1 ? 4 : 2,
      maximumFractionDigits: value < 0.1 ? 4 : 2,
    }).format(value)
  }
  return new Intl.NumberFormat(locale.value, { maximumFractionDigits: 0 }).format(value)
}

function formatDate(value: string): string {
  const [year = 0, month = 1, day = 1] = value.split('-').map(Number)
  return new Intl.DateTimeFormat(locale.value, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(year, month - 1, day)))
}

function formatAxis(value: number): string {
  if (props.metric === 'cost') {
    return `$${value.toLocaleString(locale.value, { maximumFractionDigits: value < 1 ? 2 : 1 })}`
  }
  return Intl.NumberFormat(locale.value, { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}
</script>

<style scoped>
.usage-chart { min-width: 0; }

.usage-chart__legend {
  display: flex;
  min-height: 34px;
  gap: 8px 18px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.usage-chart__legend-item { display: inline-flex; min-width: 0; gap: 6px; align-items: center; color: #3a4660; font-size: 0.76rem; }
body.body--dark .usage-chart__legend-item { color: #b6c0d4; }
.usage-chart__dot { flex: 0 0 9px; width: 9px; height: 9px; border-radius: 50%; }
.usage-chart__legend-label { max-width: 180px; overflow: hidden; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.usage-chart__provider { color: #9aa3b5; font-size: 0.7rem; }

.usage-chart__canvas { position: relative; min-height: 260px; }
.usage-chart__canvas svg { display: block; width: 100%; min-width: 620px; }
.usage-chart__grid { stroke: #e8ecf3; stroke-width: 1; stroke-dasharray: 3 5; }
.usage-chart__axis-label { fill: #8994a9; font-family: inherit; font-size: 11px; }
.usage-chart__day-label { font-weight: 600; }
.usage-chart__bar { opacity: 0.92; transition: opacity 0.18s ease; }
.usage-chart__bar:hover { opacity: 1; }

.usage-chart__empty {
  position: absolute;
  inset: 60px 0 30px 76px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  justify-content: center;
  color: #a0a9ba;
  pointer-events: none;
}

@media (max-width: 720px) {
  .usage-chart__canvas { overflow-x: auto; }
  .usage-chart__provider { display: none; }
}
</style>
