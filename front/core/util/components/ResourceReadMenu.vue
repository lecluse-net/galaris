<template>
  <q-menu :id="menuId" ref="menu" v-model="visible" :target="root ?? false" no-parent-event touch-position :transition-duration="0">
    <q-list dense role="menu" :aria-label="t('common.actions')">
      <q-item v-close-popup clickable role="menuitem" @click="emit('open', uri)"><q-item-section avatar><q-icon name="visibility" /></q-item-section><q-item-section>{{ t('richEditor.open') }}</q-item-section></q-item>
      <q-item v-close-popup clickable role="menuitem" @click="copy(uri)"><q-item-section avatar><q-icon name="link" /></q-item-section><q-item-section>{{ t('richEditor.copy') }}</q-item-section></q-item>
    </q-list>
  </q-menu>
</template>
<script setup lang="ts">
import { ref, useTemplateRef, watch } from 'vue'
import type { QMenu } from 'quasar'
import { useI18n } from 'vue-i18n'
import { richLinkTarget } from '../richText'
import { useResourceCopy } from '../resourceCopy'
import { useContextMenuDismissal } from '../contextMenuDismissal'
const { root, content } = defineProps<{ root: HTMLElement | null; content: string }>()
const emit = defineEmits<{ open: [uri: string] }>()
const { t } = useI18n(), { copy } = useResourceCopy()
const visible = ref(false), uri = ref(''), menu = useTemplateRef<QMenu>('menu')
const menuId = useContextMenuDismissal(visible, () => menu.value)
function show(event: MouseEvent | KeyboardEvent): void {
  if (event.defaultPrevented || window.getSelection()?.toString() || !(event.target instanceof Element)) return
  if (event instanceof KeyboardEvent && event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return
  const link = event.target.closest('a') ?? event.target.closest('.galaris-link-card')?.querySelector('a')
  const value = link?.getAttribute('data-rich-reference') ?? link?.getAttribute('href') ?? ''
  if (!richLinkTarget(value)) return
  event.preventDefault(); event.stopPropagation(); uri.value = value
  document.dispatchEvent(new CustomEvent('galaris-context-menu', { detail: menuId }))
  const rect = link!.getBoundingClientRect()
  menu.value?.show(event instanceof MouseEvent ? event : new MouseEvent('contextmenu', { clientX: rect.left, clientY: rect.bottom }))
}
watch(() => root, (element, _, cleanup) => {
  if (!element) return
  const close = (event: Event): void => { if ((event as CustomEvent).detail !== menuId) menu.value?.hide() }
  element.addEventListener('contextmenu', show); element.addEventListener('keydown', show)
  document.addEventListener('galaris-context-menu', close)
  cleanup(() => { element.removeEventListener('contextmenu', show); element.removeEventListener('keydown', show); document.removeEventListener('galaris-context-menu', close) })
}, { immediate: true })
watch(() => content, () => menu.value?.hide())
</script>
