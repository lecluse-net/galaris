<template>
  <q-drawer
    v-model="drawerOpen"
    show-if-above
    bordered
    :mini="isMini"
    :width="isMini ? 80 : 260"
    class="sidebar-drawer"
    :class="{ 'sidebar-mini': isMini }"
  >
    <div class="sidebar-wrapper">
      <!-- Sidebar header. -->
      <div
        class="sidebar-header shadow-3"
        :class="environmentLabel ? 'sidebar-header--edition' : 'text-white'"
        :style="environmentStyle"
      >
        <div class="header-content" :class="{ 'mini': isMini }">
          <template v-if="!isMini">
            <router-link to="/" class="logo-section" :aria-label="$t('nav.home')">
              <div class="logo-back">
                <img src="/logo/48.png" :alt="settings.APP_LABEL" class="app-logo" />
              </div>
              <span class="app-identity">
                <span class="app-name">{{ settings.APP_LABEL }}</span>
                <EnvironmentBadge />
              </span>
            </router-link>
            <q-btn
              flat
              dense
              round
              icon="menu_open"
              :aria-label="$t('index.sidebar.collapse')"
              @click="toggleMini"
            >
              <q-tooltip>{{ $t('index.sidebar.collapse') }}</q-tooltip>
            </q-btn>
          </template>
          <template v-else>
            <q-btn
              flat
              dense
              round
              icon="menu"
              :aria-label="$t('index.sidebar.expand')"
              @click="toggleMini"
            >
              <q-tooltip>{{ $t('index.sidebar.expand') }}</q-tooltip>
            </q-btn>
            <EnvironmentBadge compact />
          </template>
        </div>
      </div>

      <div class="sidebar-content" :class="{ 'content-mini': isMini }">
        <!-- Purpose-based navigation sections. -->
        <template v-if="!isMini">
          <template v-for="section in visibleNavigationSections" :key="section.rootKey">
            <div class="menu-section">
              <q-item-label
                v-if="section.label"
                header
                class="menu-section-title text-grey-8 q-pt-md"
              >
                {{ $t(section.label) }}
              </q-item-label>
              <LeftMenu :root-key="section.rootKey" />
            </div>
          </template>
        </template>

        <!-- Compact mode. -->
        <div v-if="isMini" class="mini-menu">
          <template v-for="section in visibleNavigationSections" :key="section.rootKey">
            <LeftMenu :root-key="section.rootKey" :mini="isMini" />
          </template>
        </div>
      </div>
      <SidebarFooter :compact="isMini" />
    </div>
  </q-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import LeftMenu from '@/core/navigation/components/LeftMenu.vue'
import { useAppStore } from '@/app/index/stores/appStore'
import { useNavigation } from '@/core/navigation'
import { settings } from '@/core/settings'
import { navigationSections } from '../navigationSections'
import EnvironmentBadge from './EnvironmentBadge.vue'
import SidebarFooter from './SidebarFooter.vue'
import { environmentLabel, environmentStyle } from '../environmentPresentation'

const appStore = useAppStore()
const { allTrees } = useNavigation()

/** Hide sections whose entries are all filtered out by RBAC or availability. */
const visibleNavigationSections = computed(() => navigationSections.filter((section) => {
  const rootNode = allTrees.value[section.rootKey]
  return rootNode?.children && Object.keys(rootNode.children).length > 0
}))

/** Drawer state synchronized with the store. */
const drawerOpen = computed({
  get: () => appStore.sidebarOpen,
  set: (value) => {
    if (value !== appStore.sidebarOpen) {
      appStore.toggleSidebar()
    }
  }
})

/** Compact sidebar mode. */
const isMini = computed(() => appStore.sidebarMini)

/** Toggle compact mode. */
function toggleMini() {
  appStore.toggleSidebarMini()
}
</script>

<style scoped>
.sidebar-drawer :deep(.q-drawer__content) {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.sidebar-wrapper {
  display: flex;
  flex-direction: column;
  height: 100%;
  position: relative;
  overflow: hidden;
}

.sidebar-wrapper::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: url('/background.jpg');
  background-size: cover;
  background-position: center;
  opacity: 0.06;
  z-index: 0;
  pointer-events: none;
}

.sidebar-wrapper > * {
  position: relative;
  z-index: 1;
}

body.body--dark .sidebar-header {
  box-shadow: none;
}

.sidebar-header {
  flex-shrink: 0;
  padding: 8px 12px;
  min-height: 48px;
  position: relative;
  overflow: hidden;
  backdrop-filter: blur(8px);
}

.sidebar-header::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image: url('/background.jpg');
  background-position: center;
  z-index: 0;
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: all 0.3s ease;
  position: relative;
  z-index: 1;
}

.sidebar-header--edition::after {
  display: none;
}

.app-identity {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}

.sidebar-header--edition .app-name {
  font-size: 1.25rem;
  line-height: 1.2;
  margin-bottom: 3px;
}

.sidebar-header--edition .logo-section:hover .app-name {
  color: inherit;
}

.sidebar-header--edition .logo-section:focus-visible {
  outline-color: currentColor;
}

.sidebar-header--edition .header-content.mini {
  flex-direction: column;
  gap: 3px;
}

.header-content.mini {
  justify-content: center;
}

.logo-section {
  display: flex;
  align-items: center;
  gap: 10px;
  color: inherit;
  border-radius: 8px;
  text-decoration: none;
}

.logo-section:hover .app-name {
  color: #72e1cd;
}

.logo-section:focus-visible {
  outline: 2px solid #72e1cd;
  outline-offset: 4px;
}

.app-logo {
  height: 32px;
  width: auto;
}

.app-logo-mini {
  height: 28px;
  width: auto;
}

.app-name {
  font-size: 1.6rem;
  font-weight: bold;
}

.logo-back {
  background-color: white;
  padding-top: 3px;
  width: 40px;
  text-align: center;
  vertical-align: middle;
  border-radius: 8px;
  height: 38px;
}

.sidebar-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.menu-section {
  padding: 0 8px;
}

.menu-section-title {
  padding-bottom: 10px;
}
</style>
