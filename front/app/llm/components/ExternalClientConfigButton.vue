<template>
  <q-btn
    v-if="allowed"
    outline
    color="primary"
    icon="terminal"
    :label="t('clientConfig.generate')"
    @click="open = true"
  />
  <ExternalClientConfigDialog v-if="allowed && open" @close="open = false" />
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'

const ExternalClientConfigDialog = defineAsyncComponent(() => import('./ExternalClientConfigDialog.vue'))
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const allowed = computed(() => privilegeStore.hasPrivilege(privileges.LLM_API_ACCESS))
const open = ref(false)
watch(allowed, value => { if (!value) open.value = false })
</script>
