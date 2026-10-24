<template>
  <q-page class="q-pa-md">
    <PageHeader help-key="tools" :help-text="$t('contextHelpPages.tools')" :icon="navigationIcon('build')" :title="$t('nav.tools')" :description="$t('nav.tools_desc')" />

    <q-tabs
      v-model="tab"
      dense
      align="left"
      class="text-primary tools-tabs"
      active-color="primary"
      indicator-color="primary"
    >
      <q-tab v-if="canView('tools')" name="tools" icon="build" :label="$t('tools.tabTools')" />
      <q-tab v-if="canView('connections')" name="connections" icon="link" :label="$t('tools.tabConnections')" />
      <q-tab v-if="canView('authorizations')" name="authorizations" icon="shield" :label="$t('tools.tabAuthorizations')" />
    </q-tabs>
    <q-separator />

    <q-tab-panels v-model="tab" animated keep-alive class="bg-transparent">
      <q-tab-panel v-if="canView('tools')" name="tools" class="q-px-none">
        <ToolsList />
      </q-tab-panel>
      <q-tab-panel v-if="canView('connections')" name="connections" class="q-px-none">
        <ConnectionList />
      </q-tab-panel>
      <q-tab-panel v-if="canView('authorizations')" name="authorizations" class="q-px-none">
        <AuthorizationManager />
      </q-tab-panel>
    </q-tab-panels>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, ref, watch } from 'vue'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { useRoute } from 'vue-router'
import { PageHeader } from '@/core/util'
import ToolsList from '../components/ToolsList.vue'
import ConnectionList from '@/app/connection/components/ConnectionList.vue'
import AuthorizationManager from '@/app/connection/components/AuthorizationManager.vue'

const route = useRoute()

// Select Tools by default while allowing direct links through the tab query parameter.
const privilegeStore = usePrivilegeStore()
const allowed = computed(() => ({
  tools: privilegeStore.hasAnyPrivilege([privileges.TOOL_ACCESS, privileges.TOOL_EDIT]),
  connections: privilegeStore.hasAnyPrivilege([privileges.CONNECTION_ACCESS, privileges.CONNECTION_EDIT]),
  authorizations: privilegeStore.hasAnyPrivilege([privileges.PERMISSION_ACCESS, privileges.PERMISSION_DECIDE, privileges.PERMISSION_REVOKE]),
}))
type ToolTab = keyof typeof allowed.value
const canView = (value: ToolTab) => allowed.value[value]
const allowedTabs = computed(() => (Object.keys(allowed.value) as ToolTab[]).filter(key => allowed.value[key]))
const tab = ref(
  typeof route.query.tab === 'string' && allowedTabs.value.includes(route.query.tab as ToolTab)
    ? route.query.tab
    : (allowedTabs.value[0] ?? 'tools')
)
watch(allowedTabs, tabs => {
  if (!tabs.includes(tab.value as ToolTab)) tab.value = tabs[0] ?? 'tools'
}, { immediate: true })
</script>

<style scoped>
@media (max-width: 1023px) {
  .tools-tabs :deep(.q-tabs__content) {
    justify-content: stretch;
  }

  .tools-tabs :deep(.q-tab) {
    flex: 1 1 0;
    min-width: 0;
    padding: 0 4px;
  }

  .tools-tabs :deep(.q-tab__content) {
    min-width: 0;
  }

  .tools-tabs :deep(.q-tab__label) {
    overflow: hidden;
    font-size: 0.75rem;
    text-overflow: ellipsis;
  }
}
</style>
