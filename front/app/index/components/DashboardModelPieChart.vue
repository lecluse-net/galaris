<template>
  <div class="pie-chart">
    <svg
      viewBox="0 0 200 200"
      role="img"
      :aria-label="ariaLabel"
      class="pie-chart__svg"
    >
      <g
        v-for="segment in segments"
        :key="segment.key"
        class="pie-chart__segment"
        :class="{
          'pie-chart__segment--active': activeKey === segment.key,
          'pie-chart__segment--muted': activeKey !== null && activeKey !== segment.key,
        }"
        tabindex="0"
        @mouseenter="activeKey = segment.key"
        @mouseleave="activeKey = null"
        @focus="activeKey = segment.key"
        @blur="activeKey = null"
      >
        <circle
          v-if="segment.isFullCircle"
          cx="100"
          cy="100"
          r="84"
          :fill="segment.color"
        >
          <title>{{ segment.tooltip }}</title>
        </circle>
        <path
          v-else
          :d="segment.path"
          :fill="segment.color"
        >
          <title>{{ segment.tooltip }}</title>
        </path>
      </g>
      <circle cx="100" cy="100" r="83" class="pie-chart__shine" aria-hidden="true" />
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

export interface ModelPieSlice {
  key: string
  label: string
  share: number
  color: string
}

interface PieSegment extends ModelPieSlice {
  isFullCircle: boolean
  path: string
  tooltip: string
}

const { slices, ariaLabel } = defineProps<{
  slices: ModelPieSlice[]
  ariaLabel: string
}>()

const activeKey = defineModel<string | null>('activeKey', { default: null })

const segments = computed<PieSegment[]>(() => {
  let cursor = 0
  return slices
    .filter(slice => slice.share > 0)
    .map((slice, index, filteredSlices) => {
      const start = cursor
      const end = index === filteredSlices.length - 1 ? 1 : Math.min(1, cursor + slice.share)
      cursor = end
      return {
        ...slice,
        isFullCircle: end - start >= 0.999999,
        path: createSlicePath(start, end),
        tooltip: `${slice.label} — ${formatShare(slice.share)}`,
      }
    })
})

function createSlicePath(start: number, end: number): string {
  const startPoint = pointOnCircle(start)
  const endPoint = pointOnCircle(end)
  const largeArcFlag = end - start > 0.5 ? 1 : 0
  return [
    'M 100 100',
    `L ${startPoint.x} ${startPoint.y}`,
    `A 84 84 0 ${largeArcFlag} 1 ${endPoint.x} ${endPoint.y}`,
    'Z',
  ].join(' ')
}

function pointOnCircle(position: number): { x: number; y: number } {
  const angle = position * Math.PI * 2 - Math.PI / 2
  return {
    x: 100 + 84 * Math.cos(angle),
    y: 100 + 84 * Math.sin(angle),
  }
}

function formatShare(share: number): string {
  return `${(share * 100).toFixed(1).replace('.0', '')} %`
}
</script>

<style scoped>
.pie-chart { display: grid; width: min(100%, 300px); aspect-ratio: 1; margin: 0 auto; place-items: center; }
.pie-chart__svg { width: 100%; height: 100%; overflow: visible; filter: drop-shadow(0 12px 18px rgba(45, 53, 85, 0.12)); }
.pie-chart__segment { cursor: default; outline: none; transform-box: fill-box; transform-origin: center; transition: opacity 160ms ease, transform 160ms ease; }
.pie-chart__segment path,
.pie-chart__segment circle { stroke: white; stroke-width: 2px; }
.pie-chart__segment--active { transform: scale(1.035); }
.pie-chart__segment--muted { opacity: 0.58; }
.pie-chart__segment:focus-visible path,
.pie-chart__segment:focus-visible circle { stroke: #273650; stroke-width: 3px; }
.pie-chart__shine { fill: none; stroke: rgba(255, 255, 255, 0.2); stroke-width: 1px; pointer-events: none; }
</style>
