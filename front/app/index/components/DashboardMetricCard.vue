<template>
  <q-card flat class="metric-card" :class="`metric-card--${tone}`">
    <q-card-section class="metric-card__body">
      <div class="metric-card__icon">
        <q-icon :name="icon" size="25px" />
      </div>
      <div class="metric-card__content">
        <div class="metric-card__label">{{ label }}</div>
        <div class="metric-card__value-row">
          <div class="metric-card__value">{{ value }}</div>
          <div v-if="detail" class="metric-card__detail">{{ detail }}</div>
        </div>
        <div class="metric-card__foot">
          <span v-if="trend !== null" class="metric-card__trend" :class="trendClass">
            <q-icon :name="trendIcon" size="16px" />
            {{ formattedTrend }}
          </span>
          <span v-else class="metric-card__trend metric-card__trend--neutral">—</span>
          <span class="metric-card__hint">{{ hint }}</span>
        </div>
      </div>
    </q-card-section>
  </q-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  label: string
  value: string
  icon: string
  tone: 'blue' | 'violet' | 'teal' | 'amber'
  trend: number | null
  hint: string
  detail?: string
  inverseTrend?: boolean
}>()

const isPositive = computed(() => {
  if (props.trend === null || props.trend === 0) return null
  const increasing = props.trend > 0
  return props.inverseTrend ? !increasing : increasing
})

const trendClass = computed(() => {
  if (isPositive.value === null) return 'metric-card__trend--neutral'
  return isPositive.value ? 'metric-card__trend--positive' : 'metric-card__trend--negative'
})

const trendIcon = computed(() => {
  if (props.trend === null || props.trend === 0) return 'remove'
  return props.trend > 0 ? 'north_east' : 'south_east'
})

const formattedTrend = computed(() => {
  if (props.trend === null) return '—'
  return `${Math.abs(props.trend).toLocaleString(undefined, { maximumFractionDigits: 1 })} %`
})
</script>

<style scoped>
.metric-card {
  position: relative;
  height: 100%;
  overflow: hidden;
  border: 1px solid rgba(35, 50, 84, 0.08);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 10px 32px rgba(31, 45, 75, 0.07);
}

.metric-card::before {
  position: absolute;
  inset: 0 auto 0 0;
  width: 4px;
  content: '';
  background: var(--metric-color);
}

.metric-card--blue { --metric-color: #4f7cff; --metric-soft: #edf2ff; }
.metric-card--violet { --metric-color: #8b5cf6; --metric-soft: #f3efff; }
.metric-card--teal { --metric-color: #10a78e; --metric-soft: #e8f8f4; }
.metric-card--amber { --metric-color: #e79525; --metric-soft: #fff5e4; }

body.body--dark .metric-card { border-color: rgba(255, 255, 255, 0.09); background: rgba(29, 29, 29, 0.94); box-shadow: 0 10px 32px rgba(0, 0, 0, 0.35); }
body.body--dark .metric-card--blue { --metric-soft: #1e2740; }
body.body--dark .metric-card--violet { --metric-soft: #2b2340; }
body.body--dark .metric-card--teal { --metric-soft: #17302b; }
body.body--dark .metric-card--amber { --metric-soft: #362b15; }

.metric-card__body {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  padding: 20px;
}

.metric-card__icon {
  display: grid;
  flex: 0 0 46px;
  width: 46px;
  height: 46px;
  color: var(--metric-color);
  background: var(--metric-soft);
  border-radius: 14px;
  place-items: center;
}

.metric-card__content { min-width: 0; flex: 1; }
.metric-card__label { color: #73809a; font-size: 0.78rem; font-weight: 700; letter-spacing: 0.055em; text-transform: uppercase; }
.metric-card__value-row { display: flex; gap: 12px; align-items: center; justify-content: space-between; }
.metric-card__value { margin: 5px 0 8px; color: #17233f; font-size: clamp(1.6rem, 2.2vw, 2.15rem); font-weight: 750; line-height: 1; }
.metric-card__detail { margin-left: auto; color: #97640e; font-size: 0.9rem; font-weight: 750; font-variant-numeric: tabular-nums; text-align: right; }
body.body--dark .metric-card__value { color: #dbe2ee; }
body.body--dark .metric-card__detail { color: #d9a54a; }
body.body--dark .metric-card__trend--positive { color: #34d0ab; }
.metric-card__foot { display: flex; gap: 8px; align-items: center; color: #8a94a8; font-size: 0.78rem; }
.metric-card__trend { display: inline-flex; gap: 2px; align-items: center; font-weight: 700; white-space: nowrap; }
.metric-card__trend--positive { color: #078873; }
.metric-card__trend--negative { color: #d44d5c; }
.metric-card__trend--neutral { color: #8a94a8; }
.metric-card__hint { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
