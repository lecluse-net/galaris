<template>
    <HomePublic v-if="!authStore.isAuthenticated" />
    <q-page v-else-if="onboardingStore.loading || (!helpStore.ready && !helpStore.loadError)" class="home-loading">
      <q-spinner-orbit color="primary" size="56px" />
      <div class="text-subtitle1">{{ t('onboarding.loading') }}</div>
    </q-page>
    <WelcomePage v-else-if="onboardingStore.needsInitialSetup || !helpStore.dismissed.includes(WELCOME_DISMISSAL_KEY)" />
    <HomeActionCenter v-else />
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore, useHelpStore } from '@/core/user'
import { useOnboardingStore, WelcomePage, WELCOME_DISMISSAL_KEY } from '@/app/onboarding'
import HomeActionCenter from '../components/HomeActionCenter.vue'
import HomePublic from '../components/HomePublic.vue'

const { t } = useI18n()
const authStore = useAuthStore()
const onboardingStore = useOnboardingStore()
const helpStore = useHelpStore()

watch(
  () => authStore.isAuthenticated ? authStore.user?.id : null,
  (accountId) => {
    onboardingStore.clearState()
    if (accountId != null) {
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
