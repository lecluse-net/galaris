<template>
  <svg
    class="galaris-folder-icon"
    ref="element"
    :viewBox="`0 0 ${artworkSize} ${artworkSize}`"
    aria-hidden="true"
    focusable="false"
    :data-folder-tone="tone"
    :data-folder-expanded="expanded"
    :style="{ width: size, height: size }"
    v-html="artwork"
  />
</template>

<script setup lang="ts">
import type { SolaireColor } from '../solaire'
import { computed, onBeforeUnmount, onMounted, ref, useId, useTemplateRef } from 'vue'
import { solaireCss } from '../solaireTheme'
import { folderSvgContent } from '../folderArtwork'

const { expanded = false, size = '24px', tone = 'default' } = defineProps<{
  expanded?: boolean
  size?: string
  tone?: SolaireColor | 'default'
}>()
const id = `folder-${useId()}`
const element = useTemplateRef<SVGSVGElement>('element')
const measuredSize = ref(24)
const artworkSize = computed(() => {
  const pixels = /^\d+(?:\.\d+)?px$/.test(size) ? Number.parseFloat(size) : measuredSize.value
  return pixels <= 32 ? Math.max(16, Math.round(pixels)) : 64
})
const artwork = computed(() => folderSvgContent(tone === 'default' ? undefined : solaireCss[tone], expanded, id, artworkSize.value))
let observer: ResizeObserver | undefined
onMounted(() => {
  observer = new ResizeObserver(([entry]) => {
    if (entry && entry.contentRect.width > 0) measuredSize.value = entry.contentRect.width
  })
  if (element.value) observer.observe(element.value)
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<style scoped>
.galaris-folder-icon { display: inline-block; flex: none; vertical-align: middle; object-fit: contain; }
</style>
