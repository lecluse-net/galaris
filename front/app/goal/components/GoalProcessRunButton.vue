<template>
  <q-btn v-if="canView" outline color="primary" icon="account_tree" :label="t('goal.cycleProcess.openRun')" @click="open = true" />
  <ResourceDetailDialog v-if="open && canView" :target="target" @close="open = false" />
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { ResourceDetailDialog, type ResourceDetailTarget } from '@/core/util'

const { runReference, engine } = defineProps<{ runReference: string; engine?: string | null }>()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const isNative = computed(() => engine === 'galaris')
const canView = computed(() => privilegeStore.hasAnyPrivilege([
  privileges.PROCESS_READ,
  isNative.value ? privileges.PROCESS_EDIT : privileges.PROCESS_LAUNCH,
  privileges.PROCESS_ADMIN,
]))
const open = ref(false)
const target = computed<ResourceDetailTarget>(() => ({
  kind: isNative.value ? 'process_run' : 'external_process_run',
  id: runReference,
  title: '',
}))
</script>
