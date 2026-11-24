<template>
  <main @keydown.esc="finish(null)">
    <header class="row items-center justify-between q-pa-md bg-primary text-white">
      <h1 class="text-h6 q-ma-none">{{ initialState.title }}</h1>
      <q-btn flat round dense icon="close" :aria-label="t('screenCancel')" @click="finish(null)" />
    </header>
    <section class="q-pa-md">
      <p>{{ t('screenRequested', { agent: initialState.agent }) }}</p>
      <p class="screen-reason">{{ initialState.reason }}</p>
      <p>{{ t('screenDisclosure') }}</p>
      <template v-if="preview">
        <img class="screen-preview" :src="preview" :alt="t('screenPreview')">
      </template>
      <template v-else-if="!initialState.nativePicker">
        <q-select v-if="sources.length" outlined :options="sources" option-value="id" option-label="name"
          emit-value map-options :model-value="selected" :disable="busy"
          :label="t('screenSource')" @update:model-value="select" />
        <q-btn v-else color="primary" :label="t('screenChoose')" :loading="busy" @click="choose" />
      </template>
      <p v-if="failed" class="text-negative q-mt-md" role="alert">{{ t('screenFailed') }}</p>
    </section>
    <q-separator />
    <footer class="row justify-end q-gutter-sm q-pa-md">
      <q-btn outline color="primary" :label="t('screenCancel')" @click="finish(null)" />
      <q-btn v-if="preview" color="primary" :label="t('screenSend')" :loading="busy" @click="submit" />
      <q-btn v-else-if="selected || initialState.nativePicker" color="primary" :label="t('screenCapture')" :loading="busy" @click="capture" />
    </footer>
  </main>
</template>

<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ScreenPromptState, ScreenSource } from '../src/contracts'

defineProps<{ initialState: ScreenPromptState }>()
const { t } = useI18n()
const api = window.galarisDesktop
const sources = ref<ScreenSource[]>([])
const selected = ref('')
const preview = ref('')
const busy = ref(false)
const failed = ref(false)
let image: Blob | undefined
let running: MediaStream | undefined
let cancelled = false

async function select(id: string): Promise<void> {
  selected.value = ''
  busy.value = true
  try {
    if (await api.screenSelect(id)) selected.value = id
    else failed.value = true
  } catch { failed.value = true } finally { busy.value = false }
}

async function choose(): Promise<void> {
  busy.value = true
  failed.value = false
  try {
    sources.value = await api.screenSources()
    failed.value = !sources.value.length
  } catch { failed.value = true } finally { busy.value = false }
}

async function capture(): Promise<void> {
  busy.value = true
  failed.value = false
  const video = document.createElement('video')
  video.muted = true
  try {
    running = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false })
    if (cancelled) return
    video.srcObject = running
    await video.play()
    if (!video.videoWidth || !video.videoHeight) throw new Error('Empty screen')
    const scale = Math.min(1, 1920 / Math.max(video.videoWidth, video.videoHeight))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale))
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale))
    const context = canvas.getContext('2d')
    if (!context) throw new Error('Capture unavailable')
    context.drawImage(video, 0, 0, canvas.width, canvas.height)
    running.getTracks().forEach(track => track.stop())
    video.srcObject = null
    image = await new Promise<Blob | undefined>(resolve => canvas.toBlob(value => resolve(value ?? undefined), 'image/jpeg', 0.84))
    if (!image || image.size > 1_500_000) throw new Error('Invalid capture')
    if (!cancelled) preview.value = URL.createObjectURL(image)
  } catch {
    if (!cancelled) {
      failed.value = true
      selected.value = ''
      sources.value = []
    }
  } finally {
    running?.getTracks().forEach(track => track.stop())
    running = undefined
    video.srcObject = null
    busy.value = false
    if (!cancelled) await api.screenRestore().catch(() => {})
  }
}

async function finish(data: ArrayBuffer | null): Promise<void> {
  if (data === null) cancelled = true
  try { await api.screenFinish(data) } catch { failed.value = true }
}
async function submit(): Promise<void> {
  if (!image || cancelled) return
  busy.value = true
  try {
    const data = await image.arrayBuffer()
    if (!cancelled) await finish(data)
  } finally { busy.value = false }
}
onUnmounted(() => {
  cancelled = true
  running?.getTracks().forEach(track => track.stop())
  if (preview.value) URL.revokeObjectURL(preview.value)
})
</script>

<style scoped>
.screen-reason { overflow-wrap: anywhere; white-space: pre-wrap; }
.screen-preview { display: block; max-width: 100%; max-height: 48vh; margin-inline: auto; }
</style>
