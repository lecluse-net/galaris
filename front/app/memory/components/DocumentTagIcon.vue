<template>
  <span v-if="glyph" class="tag-unicode-icon" :style="{ fontSize: size }" aria-hidden="true">{{ glyph }}</span>
  <FolderIcon v-else-if="folder" :tone="folder.tone" :expanded="expanded" :size="size" />
  <q-icon v-else-if="fontName && fontReady" :name="fontName" :size="size" class="tag-monochrome-icon" />
  <img v-else-if="value.startsWith('data:image/svg+xml;base64,')" :src="value" alt="" :style="{ width: size, height: size }" draggable="false" />
  <q-icon v-else-if="defaultIcon" :name="defaultIcon" :size="size" class="tag-monochrome-icon" />
  <FolderIcon v-else tone="gray" :expanded="expanded" :size="size" />
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { FolderIcon, solaireColors, type SolaireColor } from '@/core/util'
import { loadTagFont, normalizedTagIcon, unicodeIcon } from '../tagIcon'
const props = withDefaults(defineProps<{ icon?: string | null; size?: string; expanded?: boolean; defaultIcon?: string }>(), { size: '24px', expanded: false })
const value = computed(() => normalizedTagIcon(props.icon))
const glyph = computed(() => unicodeIcon(value.value))
const folder = computed(() => {
  const match = value.value.match(/^(folder|folder-open):([a-z]+)$/)
  const tone = match?.[2] as SolaireColor | undefined
  return tone && solaireColors.includes(tone) ? { tone } : null
})
const font = computed(() => value.value.match(/^font:(mdi|fas|far|fab):([a-z0-9-]+)$/))
const fontName = computed(() => font.value ? (font.value[1] === 'mdi' ? `mdi-${font.value[2]}` : `${font.value[1]} fa-${font.value[2]}`) : '')
const fontReady = ref(false)
watch(font, async (current, _previous, onCleanup) => {
  let cancelled = false
  onCleanup(() => { cancelled = true })
  fontReady.value = false
  if (!current) return
  try { await loadTagFont(current[1] === 'mdi' ? 'mdi' : 'awesome'); if (!cancelled) fontReady.value = true } catch { /* Keep the default icon if a font cannot load. */ }
}, { immediate: true })
</script>
<style scoped>
.tag-monochrome-icon { color: var(--solaire-gray-accent); }
.tag-unicode-icon { font-family: 'Apple Color Emoji', 'Segoe UI Emoji', 'Noto Color Emoji', emoji, sans-serif; line-height: 1; }
</style>
