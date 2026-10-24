<template>
  <q-page
    class="authorizations-page q-pa-md"
    :class="{ 'authorizations-page--privileges': tab === 'privileges' }"
    :style-fn="pageStyle"
  >
    <PageHeader :icon="navigationIcon('security')" :title="$t('nav.authorizations')" :description="$t('nav.authorizations_desc')" />

    <q-tabs
      v-model="tab"
      active-color="primary"
      indicator-color="primary"
      align="left"
      dense
      outside-arrows
      mobile-arrows
      narrow-indicator
      class="authorization-tabs text-primary"
    >
      <q-tab v-if="canView('privileges')" name="privileges" :label="$t('authorize.tabPrivileges')" icon="vpn_key" />
      <q-tab v-if="canView('roles')" name="roles" :label="$t('authorize.tabRoles')" icon="security" />
      <q-tab v-if="canView('assignments')" name="assignments" :label="$t('authorize.tabAssignments')" icon="people" />
    </q-tabs>

    <q-separator />

    <q-tab-panels v-model="tab" animated keep-alive class="authorization-panels bg-transparent">
      <q-tab-panel v-if="canView('privileges')" name="privileges" class="privileges-panel q-pa-none">
        <PrivilegeListManager />
      </q-tab-panel>

      <q-tab-panel v-if="canView('roles')" name="roles" class="q-pa-none">
        <RoleManager />
      </q-tab-panel>

      <q-tab-panel v-if="canView('assignments')" name="assignments" class="q-pa-none">
        <AssignmentManager />
      </q-tab-panel>
    </q-tab-panels>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, ref, watch } from 'vue'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { PageHeader } from '@/core/util'
import RoleManager from '../components/RoleManager.vue'
import AssignmentManager from '../components/AssignmentManager.vue'
import PrivilegeListManager from '../components/PrivilegeListManager.vue'

const privilegeStore = usePrivilegeStore()
const allowedTabs = computed(() => ({
  roles: privilegeStore.hasAnyPrivilege([privileges.READ_ROLE, privileges.MANAGE_ROLE]),
  privileges: privilegeStore.hasAnyPrivilege([privileges.READ_PRIVILEGE, privileges.MANAGE_PRIVILEGE]),
  assignments: privilegeStore.hasAnyPrivilege([privileges.READ_ASSIGNMENT, privileges.MANAGE_ASSIGNMENT]),
}))
type AuthorizationTab = keyof typeof allowedTabs.value
const canView = (value: AuthorizationTab) => allowedTabs.value[value]
const tab = ref<AuthorizationTab>('roles')
watch(allowedTabs, allowed => {
  if (!allowed[tab.value]) tab.value = (Object.keys(allowed) as AuthorizationTab[]).find(key => allowed[key]) ?? 'roles'
}, { immediate: true })

function pageStyle(offset: number, height: number) {
  return {
    minHeight: `${height - offset}px`,
    '--authorization-page-height': `${height - offset}px`,
  }
}
</script>

<style scoped>
.authorization-tabs {
  max-width: 100%;
}

@media (min-width: 1024px) {
  .authorizations-page--privileges {
    display: flex;
    flex-direction: column;
    height: var(--authorization-page-height);
  }

  .authorizations-page--privileges > * {
    flex-shrink: 0;
  }

  .authorizations-page--privileges .authorization-panels {
    flex: 1;
    min-height: 0;
  }

  .privileges-panel {
    height: 100%;
    overflow: hidden;
  }
}

@media (max-width: 599px) {
  .authorizations-page {
    padding: 8px;
  }

  .authorization-tabs :deep(.q-tab) {
    min-width: max-content;
  }
}
</style>
