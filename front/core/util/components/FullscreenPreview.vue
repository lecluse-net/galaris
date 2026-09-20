<template>
  <Teleport to="body">
    <div
      v-if="open"
      ref="overlay"
      class="fullscreen-preview"
      :class="{ 'fullscreen-preview--controls-hidden': !interactive && !controlsVisible }"
      role="dialog"
      aria-modal="true"
      :aria-label="viewerLabel"
      tabindex="-1"
      @click.self="close"
      @mousemove="showControls"
      @pointerdown="showControls"
      @focusin="showControls"
      @keydown="showControls"
      @keydown.esc.stop.prevent="close"
      @keydown.tab="trapFocus"
    >
      <div
        v-if="!interactive && !controlsVisible"
        class="fullscreen-preview__wake-layer"
        aria-hidden="true"
        @mousemove="showControls"
        @pointerdown="showControls"
      />
      <div class="fullscreen-preview__viewer">
        <div
          class="fullscreen-preview__controls"
          role="toolbar"
          :aria-label="t('fullscreenPreview.viewControls')"
        >
          <template v-if="!spatial">
          <q-btn
            flat
            round
            dense
            icon="fit_screen"
            :color="fit ? 'primary' : 'white'"
            :aria-label="t('fullscreenPreview.fitToScreen')"
            @click="fitToScreen"
          >
            <q-tooltip>{{ t('fullscreenPreview.fitToScreen') }}</q-tooltip>
          </q-btn>
          <q-btn
            flat
            dense
            no-caps
            label="1:1"
            :color="!fit && zoom === 1 ? 'primary' : 'white'"
            :aria-label="t('fullscreenPreview.actualSize')"
            @click="showActualSize"
          >
            <q-tooltip>{{ t('fullscreenPreview.actualSize') }}</q-tooltip>
          </q-btn>
          <q-btn
            flat
            round
            dense
            icon="zoom_out"
            color="white"
            :disable="!fit && zoom <= minimumZoom"
            :aria-label="t('fullscreenPreview.zoomOut')"
            @click="changeZoom(-1)"
          >
            <q-tooltip>{{ t('fullscreenPreview.zoomOut') }}</q-tooltip>
          </q-btn>
          <output
            class="fullscreen-preview__zoom-level"
            :aria-label="t('fullscreenPreview.zoomLevel', { level: zoomLabel })"
          >
            {{ zoomLabel }}
          </output>
          <q-btn
            flat
            round
            dense
            icon="zoom_in"
            color="white"
            :disable="!fit && zoom >= maximumZoom"
            :aria-label="t('fullscreenPreview.zoomIn')"
            @click="changeZoom(1)"
          >
            <q-tooltip>{{ t('fullscreenPreview.zoomIn') }}</q-tooltip>
          </q-btn>
          </template>
          <q-btn
            v-if="fullscreenSupported"
            flat
            round
            dense
            :icon="fullscreenActive ? 'fullscreen_exit' : 'fullscreen'"
            color="white"
            :aria-label="t(fullscreenActive ? 'fullscreenPreview.exitFullscreen' : 'fullscreenPreview.fullscreen')"
            @click="toggleFullscreen"
          >
            <q-tooltip>
              {{ t(fullscreenActive ? 'fullscreenPreview.exitFullscreen' : 'fullscreenPreview.fullscreen') }}
            </q-tooltip>
          </q-btn>
          <slot name="actions" />
          <q-btn flat round dense icon="close" color="white" :aria-label="t('common.close')" @click="close">
            <q-tooltip>{{ t('common.close') }}</q-tooltip>
          </q-btn>
        </div>

        <main class="fullscreen-preview__content" @click.self="close">
          <div
            class="fullscreen-preview__stage"
            :class="{
              'fullscreen-preview__stage--fit': fit,
              'fullscreen-preview__stage--immersive': immersive,
            }"
            :style="stageStyle"
            @click.self="close"
          >
            <slot :fit="fit" :zoom="zoom" />
          </div>
        </main>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const { immersive = false, interactive = false, spatial = false, viewerLabel } = defineProps<{
  immersive?: boolean
  interactive?: boolean
  spatial?: boolean
  viewerLabel: string
}>()
const open = defineModel<boolean>({ required: true })
const { t } = useI18n()
const overlay = useTemplateRef<HTMLDivElement>('overlay')
const fit = ref(true)
const zoom = ref(1)
const controlsVisible = ref(true)
const fullscreenSupported = ref(false)
const fullscreenActive = ref(false)
const zoomSteps = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4] as const
const minimumZoom = zoomSteps[0]
const maximumZoom = zoomSteps[zoomSteps.length - 1]
const stageStyle = computed((): Record<string, string> => fit.value || spatial ? {} : { zoom: String(zoom.value) })
const zoomLabel = computed(() => (
  fit.value ? t('fullscreenPreview.fitLabel') : `${Math.round(zoom.value * 100)}%`
))
let controlsTimer: ReturnType<typeof setTimeout> | undefined
let trigger: HTMLElement | null = null
let previousBodyOverflow = ''

function clearControlsTimer(): void {
  if (!controlsTimer) return
  clearTimeout(controlsTimer)
  controlsTimer = undefined
}

function showControls(): void {
  controlsVisible.value = true
  clearControlsTimer()
  if (!open.value || interactive) return
  controlsTimer = setTimeout(() => {
    controlsTimer = undefined
    if (open.value) controlsVisible.value = false
  }, 2_000)
}

function fitToScreen(): void {
  fit.value = true
  zoom.value = 1
}

function showActualSize(): void {
  fit.value = false
  zoom.value = 1
}

function changeZoom(direction: -1 | 1): void {
  const current = fit.value ? 1 : zoom.value
  const currentIndex = zoomSteps.findIndex(step => step >= current)
  const baseIndex = currentIndex < 0 ? zoomSteps.length - 1 : currentIndex
  const nextIndex = Math.min(zoomSteps.length - 1, Math.max(0, baseIndex + direction))
  fit.value = false
  zoom.value = zoomSteps[nextIndex] ?? 1
}

async function toggleFullscreen(): Promise<void> {
  const element = overlay.value
  if (!element || !fullscreenSupported.value) return
  try {
    if (document.fullscreenElement === element) await document.exitFullscreen()
    else await element.requestFullscreen()
  } catch {
    // Browsers may reject fullscreen when the user gesture is no longer active.
  }
}

async function close(): Promise<void> {
  if (document.fullscreenElement === overlay.value) {
    await document.exitFullscreen().catch(() => undefined)
  }
  open.value = false
}

function onFullscreenChange(): void {
  fullscreenActive.value = document.fullscreenElement === overlay.value
  showControls()
}

function trapFocus(event: KeyboardEvent): void {
  const root = overlay.value
  if (!root) return
  const focusable = [...root.querySelectorAll<HTMLElement>(
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )].filter(element => element.offsetParent !== null)
  if (!focusable.length) {
    event.preventDefault()
    root.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}

watch(open, async isOpen => {
  clearControlsTimer()
  controlsVisible.value = true
  if (isOpen) {
    trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
    previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    fitToScreen()
    await nextTick()
    overlay.value?.focus()
    showControls()
    return
  }
  document.body.style.overflow = previousBodyOverflow
  if (document.fullscreenElement === overlay.value) {
    void document.exitFullscreen().catch(() => undefined)
  }
  const previousTrigger = trigger
  trigger = null
  await nextTick()
  previousTrigger?.focus()
})

onMounted(() => {
  fullscreenSupported.value = document.fullscreenEnabled
  document.addEventListener('fullscreenchange', onFullscreenChange)
})

onBeforeUnmount(() => {
  clearControlsTimer()
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  if (open.value) document.body.style.overflow = previousBodyOverflow
})
</script>

<style scoped>
.fullscreen-preview { position: fixed; inset: 0; z-index: 7000; overflow: hidden; background: rgba(0, 0, 0, .82); backdrop-filter: blur(3px); outline: none; }
.fullscreen-preview__wake-layer { position: fixed; inset: 0; z-index: 7001; cursor: none; }
.fullscreen-preview__viewer { position: absolute; inset: 0; display: grid; grid-template-rows: minmax(0, 1fr); color: #fff; }
.fullscreen-preview__controls { position: relative; grid-area: 1 / 1; align-self: start; justify-self: end; margin: 10px; z-index: 7002; display: flex; max-width: calc(100vw - 20px); align-items: center; gap: 2px; padding: 4px 6px; overflow-x: auto; color: #fff; background: rgba(0, 0, 0, .68); border: 1px solid rgba(255, 255, 255, .16); border-radius: 24px; box-shadow: 0 3px 14px rgba(0, 0, 0, .35); scrollbar-width: none; transition: opacity .2s ease, transform .2s ease; }
.fullscreen-preview__controls::-webkit-scrollbar { display: none; }
.fullscreen-preview--controls-hidden .fullscreen-preview__controls { pointer-events: none; opacity: 0; transform: translateY(-10px); }
.fullscreen-preview__zoom-level { min-width: 58px; padding: 4px 7px; color: #fff; font-family: inherit; font-size: .72rem; font-weight: 600; line-height: 1.2; text-align: center; }
.fullscreen-preview__content { position: relative; grid-area: 1 / 1; min-height: 0; padding: 0; overflow: auto; container-type: size; color: #fff; background: transparent; }
.fullscreen-preview__stage { --galaris-preview-height: 100cqh; width: 100%; min-height: 100%; transform-origin: top left; }
.fullscreen-preview__stage--fit.fullscreen-preview__stage--immersive { display: flex; min-height: 100%; align-items: center; justify-content: center; }
.fullscreen-preview__stage:not(.fullscreen-preview__stage--fit) { width: max-content; min-width: 100%; }

@media (max-width: 599px) {
  .fullscreen-preview__controls { justify-self: center; justify-content: safe center; }
}
</style>
