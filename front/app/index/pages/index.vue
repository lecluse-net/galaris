<template>
    <HomePublic v-if="!authStore.isAuthenticated" />
    <q-page v-else-if="onboardingStore.loading" class="home-loading">
      <q-spinner-orbit color="primary" size="56px" />
      <div class="text-subtitle1">{{ t('onboarding.loading') }}</div>
    </q-page>
    <WelcomePage v-else-if="!onboardingStore.error && onboardingStore.needsInitialSetup" />
    <HomeActionCenter v-else />
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/core/user'
import { useOnboardingStore, WelcomePage } from '@/app/onboarding'
import HomeActionCenter from '../components/HomeActionCenter.vue'
import HomePublic from '../components/HomePublic.vue'

const { t } = useI18n()
const authStore = useAuthStore()
const onboardingStore = useOnboardingStore()

watch(
  () => authStore.isAuthenticated,
  (isAuthenticated) => {
    if (isAuthenticated) {
      void onboardingStore.fetchOverview()
    } else {
      onboardingStore.clearState()
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
