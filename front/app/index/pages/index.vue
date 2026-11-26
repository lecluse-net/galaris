<template>
    <HomePublic v-if="!authStore.isAuthenticated" />
    <HomeUser v-else-if="!isAdministrator" :key="authStore.user?.id" />
    <q-page v-else-if="privilegeStore.loading || (canConfigureSetup && (onboardingStore.loading || (!helpStore.ready && !helpStore.loadError)))" class="home-loading">
      <q-spinner-orbit color="primary" size="56px" />
      <div class="text-subtitle1">{{ t('onboarding.loading') }}</div>
    </q-page>
    <WelcomePage v-else-if="canConfigureSetup && (hasMissingSetup || !helpStore.dismissed.includes(WELCOME_DISMISSAL_KEY))" />
    <HomeActionCenter v-else />
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthorizeStore, usePrivilegeStore } from '@/core/authorize'
import { useAuthStore, useHelpStore } from '@/core/user'
import { useOnboardingStore, useSetupAccess, WelcomePage, WELCOME_DISMISSAL_KEY } from '@/app/onboarding'
import HomeActionCenter from '../components/HomeActionCenter.vue'
import HomePublic from '../components/HomePublic.vue'
import HomeUser from '../components/HomeUser.vue'

const { t } = useI18n()
const authStore = useAuthStore()
const onboardingStore = useOnboardingStore()
const helpStore = useHelpStore()
const privilegeStore = usePrivilegeStore()
const authorizeStore = useAuthorizeStore()
const isAdministrator = computed(() => authorizeStore.activeRole?.code === 'admin')
const { canConfigureSetup, hasMissingSetup } = useSetupAccess()

watch(
  [() => authStore.isAuthenticated ? authStore.user?.id : null, isAdministrator, canConfigureSetup],
  ([accountId, isAdmin, canConfigure]) => {
    onboardingStore.clearState()
    if (accountId != null && isAdmin && canConfigure) {
      void onboardingStore.fetchOverview()
      void helpStore.load()
    }
  },
  { immediate: true },
)
</script>

<style scoped>
.home-loading {
  display: flex;
  min-height: min(70vh, 680px);
  flex-direction: column;
  gap: 18px;
  align-items: center;
  justify-content: center;
  color: #60708e;
}
</style>
