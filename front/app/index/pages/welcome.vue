<template>
  <WelcomePage />
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { useAuthStore } from '@/core/user'
import { useOnboardingStore, WelcomePage } from '@/app/onboarding'

const authStore = useAuthStore()
const onboardingStore = useOnboardingStore()

watch(
  () => authStore.isAuthenticated,
  (isAuthenticated) => {
    if (isAuthenticated) void onboardingStore.fetchOverview()
  },
  { immediate: true },
)
</script>
