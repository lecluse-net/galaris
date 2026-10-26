<route lang="json">
{ "path": "/params/files" }
</route>

<template>
  <q-page v-if="canIndex" class="q-pa-md">
    <PageHeader icon="folder_open" :title="t('configuration.pageTitle', { name: t('nav.files') })"
      :description="t('files.settingsDescription')" />
    <FileIndexSettings :key="session" v-model="selectedAgentId" />
    <q-btn outline color="primary" class="q-mt-md" icon="arrow_back" :label="t('common.back')" to="/params" />
  </q-page>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { AUTH_TOKEN_CHANGED_EVENT } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { PageHeader } from '@/core/util'
import FileIndexSettings from '../components/FileIndexSettings.vue'

const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const canIndex = computed(() => privilegeStore.hasAnyPrivilege([privileges.FILE_INDEX_ACCESS, privileges.FILE_INDEX_RUN]))
const selectedAgentId = ref<number | null>(null)
const session = ref(0)
function sessionChanged(): void {
  selectedAgentId.value = null
  session.value++
}
onMounted(() => window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged))
onBeforeUnmount(() => window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged))
</script>
