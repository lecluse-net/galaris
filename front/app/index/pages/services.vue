<route lang="json">
{ "path": "/services" }
</route>
<template>
  <q-page class="q-pa-md">
    <PageHeader help-key="tools" :help-text="$t('contextHelpPages.tools')" :icon="navigationIcon('hub')" :title="$t('nav.services')" :description="$t('nav.services_desc')" />

    <q-tabs
      v-model="tab"
      dense
      align="left"
      class="text-primary tools-tabs"
      active-color="primary"
      indicator-color="primary"
    >
      <q-tab v-if="canView('tools')" name="tools" class="services-tab" :icon="navigationIcon('hub')" :label="$t('services.tabServices')" />
      <q-tab v-if="canView('connections')" name="connections" icon="link" :label="$t('services.tabConnections')" />
      <q-tab v-if="canView('authorizations')" name="authorizations" icon="shield" :label="$t('services.tabAuthorizations')" />
    </q-tabs>
    <q-separator />

    <q-tab-panels v-model="tab" animated keep-alive class="bg-transparent">
      <q-tab-panel v-if="canView('tools')" name="tools" class="q-px-none">
        <ServicesList @deleted="connections.forgetDeletedTool" />
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
import { ServicesList } from '@/app/services'
import { ConnectionList, AuthorizationManager, useConnectionStore } from '@/app/connection'

const route = useRoute()
const connections = useConnectionStore()

// Keep existing tab query links valid when opening the Services page.
const privilegeStore = usePrivilegeStore()
const allowed = computed(() => ({
  tools: privilegeStore.hasAnyPrivilege([privileges.SERVICE_ACCESS, privileges.SERVICE_EDIT]),
  connections: privilegeStore.hasAnyPrivilege([privileges.CONNECTION_ACCESS, privileges.CONNECTION_EDIT]),
  authorizations: privilegeStore.hasAnyPrivilege([privileges.PERMISSION_ACCESS, privileges.PERMISSION_DECIDE, privileges.PERMISSION_REVOKE]),
}))
type ServiceTab = keyof typeof allowed.value
const canView = (value: ServiceTab) => allowed.value[value]
const allowedTabs = computed(() => (Object.keys(allowed.value) as ServiceTab[]).filter(key => allowed.value[key]))
const tab = ref(
  typeof route.query.tab === 'string' && allowedTabs.value.includes(route.query.tab as ServiceTab)
    ? route.query.tab
    : (allowedTabs.value[0] ?? 'tools')
)
watch([() => route.query.tab, allowedTabs], ([requested, tabs]) => {
  if (typeof requested === 'string' && tabs.includes(requested as ServiceTab)) tab.value = requested
  else if (!tabs.includes(tab.value as ServiceTab)) tab.value = tabs[0] ?? 'tools'
}, { immediate: true })
</script>

<style scoped>
.services-tab :deep(.q-tab__icon) {
  background-color: currentColor;
  mask: url('/menu-icons/hub.svg') center / contain no-repeat;
  -webkit-mask: url('/menu-icons/hub.svg') center / contain no-repeat;
}
.services-tab :deep(.q-tab__icon img) { visibility: hidden; }

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
