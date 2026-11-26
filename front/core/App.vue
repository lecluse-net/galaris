<template>
  <MainLayout />
</template>

<script setup>
import { onMounted } from 'vue'
import { useMeta } from 'quasar'
import { useBrowserTheme } from '../quasar-user-options'
import { provideContextHelp } from './user/facade'
import { MainLayout } from '@/app/index'
import { useAuthStore } from './user/facade'
import { configurePrivilegeCatalogue, useAuthorizeStore, usePrivilegeStore } from './authorize'
import { settings } from './settings'

useBrowserTheme()
useMeta({ title: settings.APP_LABEL })
configurePrivilegeCatalogue(settings.is_dev)
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
})
</script>
