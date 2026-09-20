<template>
  <AiEvaluationsPage v-if="section && canAccessSection" :section="section.key" />
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { usePrivilegeStore } from '@/core/authorize'
import AiEvaluationsPage from './ai-evaluations.vue'
import { findLabSectionBySlug } from '../presentation'
import { hasAnyPrivilege, labSectionPrivileges } from '../access'

const route = useRoute()
const router = useRouter()
const privilegeStore = usePrivilegeStore()
const section = computed(() => findLabSectionBySlug(String(route.params.section ?? '')))
const canAccessSection = computed(() => {
  const value = section.value
  return value != null && hasAnyPrivilege(
    privilegeStore.hasPrivilege,
    labSectionPrivileges[value.key],
  )
})

watch([section, () => privilegeStore.loaded, canAccessSection], ([value, loaded, allowed]) => {
  if (!value || (loaded && !allowed)) void router.replace('/lab')
}, { immediate: true })
</script>
