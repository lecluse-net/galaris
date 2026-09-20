<template>
  <section class="model3d-viewer" :aria-label="t('model3d.title', { name: source.name })">
    <canvas
      ref="canvas"
      :class="{ 'model3d-viewer__canvas--hidden': loading || error }"
      tabindex="0"
      :aria-label="t('model3d.instructions')"
      @pointerdown="canvas?.focus({ preventScroll: true })"
      @webglcontextlost.prevent="contextLost"
    />
    <div v-if="loading" class="model3d-viewer__status" role="status">
      <q-spinner color="primary" size="36px" />
      <span>{{ t('model3d.loading') }}</span>
    </div>
    <div v-else-if="error" class="model3d-viewer__status" role="alert">
      <q-icon name="view_in_ar" size="42px" />
      <span>{{ t(`model3d.errors.${error}`) }}</span>
      <q-btn outline no-caps :label="t('model3d.retry')" @click="load" />
    </div>
    <div v-else class="model3d-viewer__tools" role="toolbar" :aria-label="t('fullscreenPreview.viewControls')">
      <q-btn flat round icon="center_focus_strong" :aria-label="t('model3d.reset')" @click="view?.reset()">
        <q-tooltip>{{ t('model3d.reset') }}</q-tooltip>
      </q-btn>
      <q-btn flat round icon="remove" :aria-label="t('fullscreenPreview.zoomOut')" @click="view?.zoom(1.25)" />
      <q-btn flat round icon="add" :aria-label="t('fullscreenPreview.zoomIn')" @click="view?.zoom(0.8)" />
      <q-btn flat round icon="help_outline" :aria-label="t('model3d.controlsHelp')">
        <q-tooltip>{{ t('model3d.controlsHelp') }}</q-tooltip>
        <q-menu>
          <div class="model3d-viewer__help">
            <strong>{{ t('model3d.controlsHelp') }}</strong>
            <p v-for="action in controlHints" :key="action">{{ t(`model3d.controls.${action}`) }}</p>
          </div>
        </q-menu>
      </q-btn>
    </div>
    <div v-if="!error && !loading" class="model3d-viewer__caption">
      <strong>{{ source.name }}</strong>
      <span>{{ t('model3d.instructions') }}</span>
      <span v-if="format === 'obj'">{{ t('model3d.objMaterials') }}</span>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Model3dError, model3dFormat } from '../model3d'
import type { Model3dSource } from '../model3d'
import type { Model3dView } from '../model3dRuntime'

const { source } = defineProps<{ source: Model3dSource }>()
const { t } = useI18n()
const canvas = useTemplateRef<HTMLCanvasElement>('canvas')
const loading = ref(true)
const error = ref<string | null>(null)
const format = computed(() => model3dFormat(source.mediaType, source.name))
const controlHints = ['mouseRotate', 'mousePan', 'mouseZoom', 'keyboardRotate', 'keyboardPan', 'keyboardZoom', 'keyboardReset', 'touch'] as const
let view: Model3dView | undefined
let controller: AbortController | undefined
let observer: ResizeObserver | undefined

function release(): void {
  controller?.abort()
  observer?.disconnect()
  const previous = view
  view = undefined
  previous?.dispose()
}

function contextLost(): void {
  if (view) { release(); loading.value = false; error.value = 'webgl' }
}

async function load(): Promise<void> {
  release()
  const current = new AbortController()
  controller = current
  const currentSource = source
  loading.value = true
  error.value = null
  try {
    const { loadModel, createModelView, disposeModel } = await import('../model3dRuntime')
    const model = await loadModel(currentSource, current.signal)
    if (current.signal.aborted || !canvas.value) { disposeModel(model); return }
    view = createModelView(canvas.value, model, true)
    const resize = (): void => {
      if (canvas.value) view?.resize(canvas.value.clientWidth, canvas.value.clientHeight)
    }
    resize()
    view.reset()
    observer = new ResizeObserver(resize)
    observer.observe(canvas.value)
    loading.value = false
    await nextTick()
    // Give the scene keyboard control on opening, but do not steal focus from a toolbar in use.
    if (!current.signal.aborted && canvas.value && document.activeElement === canvas.value.closest('.fullscreen-preview')) {
      canvas.value.focus({ preventScroll: true })
    }
  } catch (cause) {
    if (!current.signal.aborted) error.value = cause instanceof Model3dError ? cause.code : 'invalid'
  } finally {
    if (!current.signal.aborted) loading.value = false
  }
}

watch(() => source.key, () => { void load() })
onMounted(() => { void load() })
onBeforeUnmount(release)
</script>

<style scoped>
.model3d-viewer { position: relative; width: calc(100vw - 24px); height: calc(var(--galaris-preview-height, 100dvh) - 84px); margin: 64px 12px 20px; overflow: hidden; border-radius: 10px; color: #244564; background: #e9eef5; }
.model3d-viewer canvas { display: block; width: 100%; height: 100%; touch-action: none; outline-offset: -3px; }
.model3d-viewer__canvas--hidden { visibility: hidden; }
.model3d-viewer__status { position: absolute; inset: 0; display: flex; flex-direction: column; gap: 16px; align-items: center; justify-content: center; padding: 24px; text-align: center; }
.model3d-viewer__tools { position: absolute; top: 8px; left: 8px; display: flex; border-radius: 24px; background: #ffffffdf; }
.model3d-viewer__caption { position: absolute; bottom: 12px; left: 12px; right: 12px; display: flex; flex-direction: column; gap: 3px; pointer-events: none; font-size: 12px; text-shadow: 0 0 5px #fff; }
.model3d-viewer__help { max-width: min(400px, 90vw); padding: 16px; font-size: 13px; }
.model3d-viewer__help p { margin: 8px 0 0; }
</style>
