<template>
  <!-- These iframe nodes stay at the same DOM location when panes/rooms change. -->
  <template v-for="editor in store.editors" :key="editor.session.id">
    <iframe v-show="visible && editor.session.workspace.id === store.activeId && !editor.showRecovery"
      :src="editor.session.url" :title="editor.session.workspace.label" :style="position"
      class="code-editor-frame" allow="clipboard-read; clipboard-write" referrerpolicy="no-referrer"
      :ref="element => setFrame(editor.session.id, element)" />
    <iframe v-if="editor.recoveryUrl" :key="editor.recoveryVersion"
      v-show="visible && editor.session.workspace.id === store.activeId && editor.showRecovery"
      :src="editor.recoveryUrl" :title="editor.session.workspace.label" :style="position"
      class="code-editor-frame code-recovery-frame" allow="clipboard-read; clipboard-write" referrerpolicy="no-referrer"
      :ref="element => setFrame(editor.session.id + ':recovery', element)" />
  </template>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch, type ComponentPublicInstance } from 'vue'
import { useAuthStore } from '@/core/user'
import { useCodeStore } from '../stores/codeStore'
const store = useCodeStore()
const auth = useAuthStore()
watch(() => auth.user?.id, () => store.reset(), { flush: 'sync' })
const bounds = ref<DOMRect | null>(null)
const layer = ref(3)
const frames = new Map<string, HTMLIFrameElement>()
function setFrame(id: string, element: Element | ComponentPublicInstance | null): void {
  if (element instanceof HTMLIFrameElement) frames.set(id, element)
  else frames.delete(id)
}
function ready(event: MessageEvent): void {
  if (!['galaris.code.ready', 'galaris.code.failed'].includes(event.data?.type) || typeof event.data?.session !== 'string') return
  const editor = store.editors.find(item => item.session.id === event.data.session)
  if (!editor || event.origin !== new URL(editor.session.url).origin) return
  const recovered = event.source === frames.get(editor.session.id + ':recovery')?.contentWindow
  if (!recovered && event.source !== frames.get(editor.session.id)?.contentWindow) return
  if (event.data.type === 'galaris.code.ready') {
    if (recovered) editor.recoveryLoaded = true
    else editor.loaded = true
    if (!editor.pendingRecoveryUrl) editor.error = false
  }
  else editor.error = true
}
const visible = computed(() => store.activeId !== null && bounds.value !== null && bounds.value.width > 0 && bounds.value.height > 0)
const position = computed(() => ({ left: `${bounds.value?.left ?? 0}px`, top: `${bounds.value?.top ?? 0}px`,
  width: `${bounds.value?.width ?? 0}px`, height: `${bounds.value?.height ?? 0}px`, zIndex: layer.value,
}))
let animation: number | undefined
let heartbeat: ReturnType<typeof setInterval> | undefined
function measure(): void {
  const element = store.anchor
  const dialog = element?.closest('.q-dialog')
  const dialogs = document.querySelectorAll('.q-dialog')
  const covered = dialog ? dialogs[dialogs.length - 1] !== dialog : dialogs.length > 0
  layer.value = dialog ? 6001 : 3
  const rect = element?.isConnected && !covered ? element.getBoundingClientRect() : null
  if (!rect || !bounds.value || ['left', 'top', 'width', 'height'].some(key => rect[key as keyof DOMRect] !== bounds.value?.[key as keyof DOMRect])) bounds.value = rect
  animation = requestAnimationFrame(measure)
}
// Retain the iframe and its buffers while hidden, without scanning the page on
// every frame. The anchor is restored when the workspace pane opens again.
watch(() => Boolean(store.anchor && store.activeId !== null && store.editors.length), tracking => {
  if (animation !== undefined) cancelAnimationFrame(animation)
  animation = undefined
  if (tracking) measure()
  else bounds.value = null
}, { immediate: true, flush: 'post' })
function protectBuffers(event: BeforeUnloadEvent): void {
  if (!store.editors.some(editor => editor.session.workspace.mode === 'edit')) return
  event.preventDefault()
}
onMounted(() => { heartbeat = setInterval(() => { void store.heartbeat() }, 30_000); window.addEventListener('beforeunload', protectBuffers); window.addEventListener('message', ready) })
onBeforeUnmount(() => { store.reset(); if (animation !== undefined) cancelAnimationFrame(animation); clearInterval(heartbeat); window.removeEventListener('beforeunload', protectBuffers); window.removeEventListener('message', ready) })
</script>

<style scoped>
.code-editor-frame { position: fixed; border: 0; background: var(--solaire-gray-light); }
body.body--dark .code-editor-frame { background: var(--solaire-gray-dark); }
</style>
