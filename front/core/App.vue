<template>
  <MainLayout />
</template>

<script setup>
import { onMounted } from 'vue'
import { provideContextHelp } from './user'
import MainLayout from '@/app/index/components/MainLayout.vue'
import { useAuthStore } from './user/stores/authStore'
import { useAuthorizeStore } from './authorize/stores/authorizeStore'
import { usePrivilegeStore } from './authorize/stores/privilegeStore'
import { settings } from './settings'

const authStore = useAuthStore()
provideContextHelp()
const authorizeStore = useAuthorizeStore()
const privilegeStore = usePrivilegeStore()

onMounted(async () => {
  // Initialize auth first (this loads token and user)
  await authStore.initializeAuth()
  // Initialize authorization store (watches token for role changes)
  authorizeStore.init()
  // Initialize privilege store (watches auth and role changes)
  privilegeStore.init()
  document.title = settings.APP_LABEL
})
</script>
