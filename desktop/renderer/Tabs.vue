<template>
  <nav class="desktop-tabs row items-center no-wrap q-px-xs" :aria-label="t('tabs')" :style="{ height: `${tabBarHeight}px`, '--desktop-page-surface': tabSurface }">
    <div class="tab-controls row items-center no-wrap">
      <q-btn flat dense round color="primary" size="sm" icon="menu" :aria-label="t('showMenu')" :title="t('showMenu')" aria-haspopup="menu" @click="api.showMenu()" />
      <q-btn flat dense round color="primary" size="sm" icon="arrow_back" :aria-label="t('back')" :title="t('back')" :disable="!state.canGoBack" @click="api.back()" />
      <q-btn flat dense round color="primary" size="sm" icon="arrow_forward" :aria-label="t('forward')" :title="t('forward')" :disable="!state.canGoForward" @click="api.forward()" />
    </div>
    <div class="tab-list row items-center no-wrap" role="tablist" :aria-label="t('tabs')" @keydown="navigate">
      <q-card v-for="tab in state.tabs" :key="tab.id" flat bordered class="tab-item row items-center no-wrap" :class="{ 'tab-item--active': state.activeId === tab.id }" @auxclick.middle.prevent="api.closeTab(tab.id)">
        <q-btn flat dense no-caps class="tab-select" role="tab" :aria-selected="state.activeId === tab.id" :tabindex="state.activeId === tab.id ? 0 : -1" :title="tab.title" :data-tab-id="tab.id" @click="api.selectTab(tab.id)">
          <q-spinner v-if="tab.loading" size="14px" class="q-mr-xs" /><span class="ellipsis">{{ tab.title }}</span>
        </q-btn>
        <q-btn flat dense round size="xs" icon="close" class="q-mr-xs" :aria-label="t('closeNamedTab', { title: tab.title })" @click="api.closeTab(tab.id)" />
      </q-card>
    </div>
    <q-btn flat dense round size="sm" icon="add" :aria-label="t('newTab')" @click="api.newTab()" />
  </nav>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import type { TabsState } from '../src/contracts'
// Kept independent of Electron's main-process module.
import { tabBarHeight } from '../src/layout'

const { t } = useI18n()
const $q = useQuasar()
const api = window.galarisDesktop
const state = ref<TabsState>({ activeId: 0, dark: null, surface: 'rgb(255, 255, 255)', canGoBack: false, canGoForward: false, tabs: [] })
const tabSurface = computed(() => state.value.dark === null ? ($q.dark.isActive ? 'var(--q-dark)' : 'white') : state.value.surface)
watch(() => state.value.dark, value => $q.dark.set(value ?? 'auto'))
let changed = false
onUnmounted(api.onTabs(value => { changed = true; state.value = value }))
void api.tabs().then(value => { if (!changed) state.value = value })
watch(() => state.value.activeId, async () => {
  await nextTick()
  document.querySelector(`[data-tab-id="${state.value.activeId}"]`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
})
async function navigate(event: KeyboardEvent): Promise<void> {
  const index = state.value.tabs.findIndex(tab => tab.id === state.value.activeId)
  let target: number | undefined
  if (event.key === 'ArrowRight') target = (index + 1) % state.value.tabs.length
  if (event.key === 'ArrowLeft') target = (index - 1 + state.value.tabs.length) % state.value.tabs.length
  if (event.key === 'Home') target = 0
  if (event.key === 'End') target = state.value.tabs.length - 1
  const tab = target === undefined ? undefined : state.value.tabs[target]
  if (!tab) return
  event.preventDefault()
  await api.selectTab(tab.id)
  await nextTick()
  document.querySelector<HTMLElement>(`[data-tab-id="${tab.id}"]`)?.focus()
}
</script>

<style scoped>
.desktop-tabs { position: relative; background: var(--solaire-gray-light); gap: 4px; }
.desktop-tabs::before { content: ''; position: absolute; left: 0; right: 0; bottom: 0; border-bottom: 1px solid rgba(0, 0, 0, 0.2); }
.body--dark .desktop-tabs { background: var(--solaire-gray-dark); }
.body--dark .desktop-tabs::before { border-color: rgba(255, 255, 255, 0.28); }
.tab-controls { flex-shrink: 0; }
.tab-controls .q-btn, .desktop-tabs > .q-btn { min-height: 26px; min-width: 24px; }
.tab-list { flex: 1; min-width: 0; height: 100%; overflow-x: auto; gap: 4px; scrollbar-width: none; }
.tab-item { position: relative; flex: 0 0 auto; height: 30px; max-width: 260px; border-radius: 7px; background: rgba(0, 0, 0, 0.035); color: inherit; }
.tab-item--active { align-self: flex-end; height: 34px; border-radius: 7px 7px 0 0; border-bottom: 0; background: var(--desktop-page-surface); }
.body--dark .tab-item { border-color: rgba(255, 255, 255, 0.28); }
.body--dark .tab-item:not(.tab-item--active) { background: rgba(255, 255, 255, 0.04); }
.tab-select { min-width: 64px; max-width: 220px; min-height: 0; height: 100%; padding: 0 10px; font-size: 14px; }
.tab-select :deep(.q-focus-helper) { border-radius: inherit; }
</style>
