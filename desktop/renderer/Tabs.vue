<template>
  <nav class="desktop-tabs row items-center no-wrap q-px-xs" :aria-label="t('tabs')" :style="{ height: `${tabBarHeight}px` }">
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
import { nextTick, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TabsState } from '../src/contracts'
// Kept independent of Electron's main-process module.
import { tabBarHeight } from '../src/layout'

const { t } = useI18n()
const api = window.galarisDesktop
const state = ref<TabsState>({ activeId: 0, tabs: [] })
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
.desktop-tabs { background: var(--solaire-gray-light); gap: 4px; }
.body--dark .desktop-tabs { background: var(--solaire-gray-dark); }
.tab-list { flex: 1; min-width: 0; overflow-x: auto; gap: 4px; }
.tab-item { flex: 0 0 auto; max-width: 260px; background: transparent; color: inherit; }
.tab-item--active { background: white; }
.body--dark .tab-item--active { background: var(--q-dark); }
.tab-select { min-width: 72px; max-width: 220px; }
</style>
