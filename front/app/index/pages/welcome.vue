<template>
  <WelcomePage v-if="!authStore.isAuthenticated || privilegeStore.loading || canViewSetup" />
  <HomeUser v-else :key="authStore.user?.id" />
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { usePrivilegeStore } from '@/core/authorize'
import { useAuthStore } from '@/core/user'
import { useOnboardingStore, useSetupAccess, WelcomePage } from '@/app/onboarding'
import HomeUser from '../components/HomeUser.vue'

const authStore = useAuthStore()
const onboardingStore = useOnboardingStore()
const privilegeStore = usePrivilegeStore()
const { canViewSetup } = useSetupAccess()

watch(
  [() => authStore.isAuthenticated ? authStore.user?.id : null, canViewSetup],
  ([accountId, canView]) => {
    onboardingStore.clearState()
    if (accountId != null && canView) void onboardingStore.fetchOverview()
  },
  { immediate: true },
)
</script>
