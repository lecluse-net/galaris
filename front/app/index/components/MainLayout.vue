<template>
  <q-layout view="lHh Lpr lFf">
    <!-- Mobile taskbar, shown only when the sidebar becomes a drawer. -->
    <q-header
      v-if="showMobileTaskbar"
      class="mobile-taskbar shadow-3"
      :class="environmentLabel ? 'mobile-taskbar--edition' : 'text-white'"
      :style="environmentStyle"
    >
      <q-toolbar class="mobile-taskbar__toolbar">
        <q-btn
          v-if="authStore.isAuthenticated"
          flat
          dense
          round
          icon="menu"
          :aria-label="$t('index.sidebar.expand')"
          @click="appStore.toggleSidebar"
        />
        <span class="mobile-taskbar__app-name">{{ settings.APP_LABEL }}</span>
        <EnvironmentBadge class="q-ml-sm" />
        <q-space />
        <UserMenu />
      </q-toolbar>
    </q-header>

    <!-- Sidebar, visible only to signed-in users. -->
    <Sidebar v-if="authStore.isAuthenticated" />

    <!-- Page container. -->
    <q-page-container
      class="page-container"
      :class="{ 'page-container--mobile': showMobileTaskbar }"
    >
      <!-- User menu in the top-right corner. -->
      <div v-if="showTopRightUserMenu && !isMobileLayout" class="user-btn-top-right">
        <UserMenu />
      </div>
      <router-view />
      <template v-if="authStore.isAuthenticated">
        <component
          :is="contribution.component"
          v-for="(contribution, index) in shellContributions"
          :key="index"
        />
      </template>
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import Sidebar from './Sidebar.vue'
import UserMenu from '@/core/user/components/UserMenu.vue'
import { shellContributions } from '../shellContributions'
import { useAppStore } from '@/app/index/stores/appStore'
import { useAuthStore } from '@/core/user/stores/authStore'
import { settings } from '@/core/settings'
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useQuasar } from 'quasar'
import EnvironmentBadge from './EnvironmentBadge.vue'
import { environmentLabel, environmentStyle } from '../environmentPresentation'

const $q = useQuasar()
const appStore = useAppStore()
const authStore = useAuthStore()
const route = useRoute()

const isMobileLayout = computed(() => $q.screen.lt.md)
const guestLoginHiddenPaths = new Set(['/', '/user/login', '/user/register'])
const normalizedPath = computed(() => route.path.replace(/\/+/g, '/').replace(/\/+$/, '') || '/')
const showTopRightUserMenu = computed(() => {
  return authStore.isAuthenticated || !guestLoginHiddenPaths.has(normalizedPath.value)
})
const showMobileTaskbar = computed(() => isMobileLayout.value && showTopRightUserMenu.value)
</script>

<style scoped>
.mobile-taskbar {
  background-image: url('/background.jpg');
  background-position: center;
  backdrop-filter: blur(8px);
}

.mobile-taskbar__toolbar {
  min-height: 62px;
  padding: 3px 12px;
}

.mobile-taskbar--edition .mobile-taskbar__app-name {
  font-size: 1.1rem;
}

.mobile-taskbar__app-name {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 25vw;
  margin-left: 8px;
  overflow: hidden;
  font-size: 1.3rem;
  font-weight: 700;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-taskbar :deep(.user-menu-wrapper) {
  max-width: 48vw;
}

.mobile-taskbar :deep(.user-info-display) {
  min-width: 0;
}

.mobile-taskbar :deep(.user-name),
.mobile-taskbar :deep(.user-role) {
  max-width: calc(48vw - 64px);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

body.body--dark .mobile-taskbar {
  box-shadow: none;
}

/* Page container targeting the nested q-page. */
.page-container :deep(.q-page:not(.messenger-page)) {
  min-height: calc(100vh - 50px) !important;
  flex-direction: column !important;
}

.page-container--mobile :deep(.q-page:not(.messenger-page)) {
  min-height: calc(100vh - 112px) !important;
}

@media (min-width: 1024px) {
  /* Opt-in pages own their scrolling; the shell and footer stay in the viewport. */
  .page-container:has(> .viewport-page--desktop) {
    display: flex;
    flex-direction: column;
    height: 100dvh;
    overflow: hidden;
  }

  .page-container:has(> .viewport-page--desktop) > :deep(.viewport-page--desktop) {
    flex: 1;
    min-height: 0 !important;
  }

  .page-container:has(> .viewport-page--desktop) > :deep(.page-footer) {
    flex-shrink: 0;
  }
}

/* Position the user menu in the top-right corner relative to the content. */
.user-btn-top-right {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-container :deep(.q-tabs .q-tab) {
  min-height: 52px;
  padding: 0 18px;
}

.page-container :deep(.q-tabs .q-tab__content) {
  flex-direction: row;
  flex-wrap: nowrap;
  gap: 8px;
}

.page-container :deep(.q-tabs .q-tab__icon) {
  margin: 0;
  font-size: 26px;
}

.page-container :deep(.q-tabs .q-tab__label) {
  font-size: 1.05rem;
  line-height: 1.2;
  margin-top: 0;
}
</style>
