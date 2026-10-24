<template>
  <span ref="anchor" class="action-context-menu" @click.stop @dblclick.stop @keydown.enter.stop @keydown.space.stop>
    <q-menu :id="menuId" ref="menu" v-model="open" :target="host ?? false" no-parent-event touch-position
      max-width="calc(100vw - 16px)" :transition-duration="0" @before-show="closeOthers">
      <q-list dense role="menu" :aria-label="label || t('common.actions')">
        <template v-for="action in actions" :key="action.key">
          <q-separator v-if="action.separator" />
          <q-item v-close-popup clickable role="menuitem" :aria-label="action.label" :aria-keyshortcuts="action.shortcut" :disable="action.disabled"
            :data-autofocus="action.key === firstEnabled ? '' : undefined"
            :class="{ 'text-negative': action.negative }" @click="run(action)">
            <q-item-section avatar><q-icon :name="action.icon" /></q-item-section>
            <q-item-section>{{ action.label }}</q-item-section>
            <q-item-section v-if="action.shortcut" side>{{ action.shortcut }}</q-item-section>
          </q-item>
        </template>
        <slot />
      </q-list>
    </q-menu>
  </span>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar, type QMenu } from 'quasar'
import { apiErrorDetail } from '@/core/api'
import type { ContextAction } from '../contextActions'
import { useContextMenuDismissal } from '../contextMenuDismissal'

const { actions, target, label = '', preserveSelection = false } = defineProps<{
  actions: ContextAction[]; target: string; label?: string; preserveSelection?: boolean
}>()
const { t } = useI18n(), $q = useQuasar()
const anchor = useTemplateRef('anchor'), menu = useTemplateRef<QMenu>('menu')
const host = shallowRef<HTMLElement>(), open = ref(false)
const menuId = useContextMenuDismissal(open, () => menu.value)
const firstEnabled = computed(() => actions.find(action => !action.disabled)?.key)
const emit = defineEmits<{ 'update:open': [value: boolean] }>()
const editing = 'input, textarea, select, [contenteditable]:not([contenteditable="false"])'
function show(event?: MouseEvent): void {
  if (!actions.length) return
  menu.value?.show(event)
}
function context(event: MouseEvent): void {
  if (event.defaultPrevented || !actions.length || !(event.target instanceof Element) || event.target.closest(editing)) return
  // An inner resource menu owns its event; a parent message must not replace it.
  if (preserveSelection && window.getSelection()?.toString()) return
  event.preventDefault(); event.stopPropagation(); show(event)
}
function keyboard(event: KeyboardEvent): void {
  if (event.defaultPrevented || event.target instanceof Element && event.target.closest(editing)) return
  if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return
  if (!actions.length) return
  event.preventDefault(); event.stopPropagation(); show()
}
async function run(action: ContextAction): Promise<void> {
  // Recheck reactive permissions/state, including changes while the menu is open.
  const current = actions.find(value => value.key === action.key)
  if (!current || current.disabled) return
  try { await current.run() }
  catch (error) { $q.notify({ type: 'negative', message: apiErrorDetail(error) ?? t('common.anError') }) }
}
function closeOthers(): void { document.dispatchEvent(new CustomEvent('galaris-context-menu', { detail: anchor.value })) }
function anotherOpened(event: Event): void { if ((event as CustomEvent).detail !== anchor.value) menu.value?.hide() }
watch(open, value => emit('update:open', value))
onMounted(() => {
  host.value = anchor.value?.parentElement?.closest<HTMLElement>(target) ?? undefined
  host.value?.addEventListener('contextmenu', context)
  host.value?.addEventListener('keydown', keyboard)
  document.addEventListener('galaris-context-menu', anotherOpened)
})
onBeforeUnmount(() => {
  host.value?.removeEventListener('contextmenu', context)
  host.value?.removeEventListener('keydown', keyboard)
  document.removeEventListener('galaris-context-menu', anotherOpened)
})
</script>
<style scoped>
.action-context-menu { display: none; }
</style>
