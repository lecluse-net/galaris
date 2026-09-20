<template>
  <svg
    class="galaris-folder-icon"
    viewBox="0 0 24 24"
    aria-hidden="true"
    focusable="false"
    :data-folder-tone="tone"
    :data-folder-expanded="expanded"
    :style="{ width: size, height: size }"
  >
    <path :fill="solaireCss[tone].accent" :d="paths.back" />
    <path :fill="solaireCss[tone].dark" opacity="0.18" :d="paths.back" />
    <path :fill="solaireCss[tone].light" :d="paths.lip" />
    <path :fill="solaireCss[tone].accent" :d="paths.front" />
    <path :fill="solaireCss[tone].dark" opacity="0.14" :d="paths.edge" />
  </svg>
</template>

<script setup lang="ts">
import type { SolaireColor } from '../solaire'
import { computed } from 'vue'
import { solaireCss } from '../solaireTheme'
import { folderArtwork } from '../folderArtwork'

const { expanded = false, size = '24px', tone = 'blue' } = defineProps<{
  expanded?: boolean
  size?: string
  tone?: SolaireColor
}>()
const paths = computed(() => folderArtwork[expanded ? 'folder-open' : 'folder'])
</script>

<style scoped>
.galaris-folder-icon { display: inline-block; flex: none; vertical-align: middle; object-fit: contain; }
</style>
