<template>
  <div
    class="tile-texture"
    :style="containerStyle"
  />
</template>

<script setup lang="ts">
import { computed, onMounted, ref, type CSSProperties } from 'vue'

interface Props {
  /** CSS container width, for example '100%', '200px', or '100vw'. */
  width?: string
  /** CSS container height, for example '100%', '200px', or '100vh'. */
  height?: string
  /** Tile size in pixels. Defaults to 16. */
  tileSize?: number
  /** Pattern color palette. Defaults to neutral grey. */
  colors?: string[]
}

const props = withDefaults(defineProps<Props>(), {
  width: '100%',
  height: '100%',
  tileSize: 16,
  colors: () => ['#e0e0e0', '#bdbdbd', '#9e9e9e', '#757575'],
})

const dataUrl = ref('')

const containerStyle = computed<CSSProperties>(() => ({
  width: props.width,
  height: props.height,
  backgroundImage: dataUrl.value ? `url(${dataUrl.value})` : 'none',
  backgroundRepeat: 'repeat',
  backgroundSize: `${props.tileSize}px ${props.tileSize}px`,
  imageRendering: 'pixelated',
}))

function generateTile(): string {
  const size = props.tileSize
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''

  const palette = props.colors
  const len = palette.length

  // Deterministic pseudo-random pattern based on a simple hash.
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const idx = (x * 3 + y * 7 + (x & y)) % len
      ctx.fillStyle = palette[idx]
      ctx.fillRect(x, y, 1, 1)
    }
  }

  return canvas.toDataURL('image/png')
}

onMounted(() => {
  dataUrl.value = generateTile()
})
</script>

<style scoped>
.tile-texture {
  display: block;
}
</style>
