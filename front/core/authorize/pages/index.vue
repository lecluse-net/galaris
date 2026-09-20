<template>
  <q-page class="authorizations-page q-pa-md">
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
      <q-tab name="privileges" :label="$t('authorize.tabPrivileges')" icon="vpn_key" />
      <q-tab name="roles" :label="$t('authorize.tabRoles')" icon="security" />
      <q-tab name="assignments" :label="$t('authorize.tabAssignments')" icon="people" />
    </q-tabs>

    <q-separator />

    <q-tab-panels v-model="tab" animated keep-alive class="bg-transparent">
      <q-tab-panel name="privileges" class="q-pa-none">
        <PrivilegeListManager />
      </q-tab-panel>

      <q-tab-panel name="roles" class="q-pa-none">
        <RoleManager />
      </q-tab-panel>

      <q-tab-panel name="assignments" class="q-pa-none">
        <AssignmentManager />
      </q-tab-panel>
    </q-tab-panels>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { ref } from 'vue'
import { PageHeader } from '@/core/util'
import RoleManager from '../components/RoleManager.vue'
import AssignmentManager from '../components/AssignmentManager.vue'
import PrivilegeListManager from '../components/PrivilegeListManager.vue'

const tab = ref('roles')
</script>

<style scoped>
.authorization-tabs {
  max-width: 100%;
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
