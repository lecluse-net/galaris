<template>
  <svg class="galaris-document-file-icon" :viewBox="`0 0 ${small ? pixels : 32} ${small ? pixels : 32}`" aria-hidden="true" focusable="false" :style="{ width: size, height: size }"
    fill="none" stroke-linecap="round" stroke-linejoin="round">
    <g v-if="small" stroke-width="1">
      <path :d="small.paper" class="document-small-paper" stroke="var(--solaire-gray-accent)" />
      <path :d="small.fold" fill="var(--solaire-gray-accent)" stroke="var(--solaire-gray-accent)" />
      <path :d="small.heading" stroke="var(--solaire-blue-accent)" stroke-linecap="butt" />
      <path :d="small.lines" class="document-small-lines" stroke-linecap="butt" />
    </g>
    <g v-else>
      <defs>
        <linearGradient :id="paperGradient" x1="8" y1="3" x2="25" y2="29" gradientUnits="userSpaceOnUse">
          <stop class="document-paper-top" />
          <stop class="document-paper-bottom" offset="1" />
        </linearGradient>
      </defs>
      <path d="M8 3.5h12l6 6v18a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2v-22a2 2 0 0 1 2-2Z" fill="var(--solaire-gray-accent)" fill-opacity=".15" />
      <path d="M8 2.5h12l6 6v18a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2v-22a2 2 0 0 1 2-2Z"
        :fill="`url(#${paperGradient})`" stroke="var(--solaire-gray-accent)" stroke-opacity=".6" />
      <path d="M20 3v4a1.5 1.5 0 0 0 1.5 1.5H26" fill="var(--solaire-gray-accent)" fill-opacity=".16"
        stroke="var(--solaire-gray-accent)" stroke-opacity=".55" />
      <path d="M10 12h6" stroke="var(--solaire-blue-accent)" stroke-width="2" />
      <path d="M10 17h12M10 21h12M10 25h8" class="document-lines" stroke-width="1.4" />
    </g>
  </svg>
</template>

<script setup lang="ts">
import { computed, useId } from 'vue'

const { size = '24px' } = defineProps<{ size?: string }>()
const paperGradient = `document-paper-${useId()}`
const pixels = computed(() => /^\d+(?:\.\d+)?px$/.test(size) ? Number.parseFloat(size) : 24)
// Draw directly on the display pixel grid instead of shrinking the detailed artwork.
const small = computed(() => {
  const n = pixels.value
  if (n > 32) return null
  const left = Math.round(n / 6) + .5, right = n - Math.round(n / 6) - .5
  const top = 1.5, bottom = n - 1.5, fold = Math.round(n / 5)
  const x = left + Math.round(n / 8), end = right - Math.round(n / 8)
  const y = (ratio: number) => Math.round(n * ratio) + .5
  return {
    paper: `M${left + 1} ${top}H${right - fold}L${right} ${top + fold}V${bottom - 1}Q${right} ${bottom} ${right - 1} ${bottom}H${left + 1}Q${left} ${bottom} ${left} ${bottom - 1}V${top + 1}Q${left} ${top} ${left + 1} ${top}Z`,
    fold: `M${right - fold} ${top}V${top + fold}H${right}Z`,
    heading: `M${x} ${y(.45)}h${Math.max(3, Math.round((end - x) * .6))}`,
    lines: `M${x} ${y(.62)}H${end}M${x} ${y(.79)}H${end}`,
  }
})
</script>

<style scoped>
.galaris-document-file-icon { display: inline-block; flex: none; vertical-align: middle; }
.document-paper-top { stop-color: #FFFFFF; }
.document-paper-bottom { stop-color: var(--solaire-gray-light); }
.document-lines { stroke: var(--solaire-gray-accent); stroke-opacity: .8; }
.document-small-paper { fill: var(--solaire-gray-light); }
.document-small-lines { stroke: var(--solaire-gray-accent); }
:global(body.body--dark) .document-small-paper { fill: var(--solaire-gray-dark); }
:global(body.body--dark) .document-small-lines { stroke: var(--solaire-gray-light); }
:global(body.body--dark) .document-paper-top { stop-color: var(--solaire-gray-dark); }
:global(body.body--dark) .document-paper-bottom { stop-color: var(--solaire-gray-dark); }
:global(body.body--dark) .document-lines { stroke: var(--solaire-gray-light); stroke-opacity: .65; }
</style>
