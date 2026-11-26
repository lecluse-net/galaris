<route lang="json">
{ "path": "/users", "alias": "/user/users" }
</route>

<template>
  <q-page
    class="users-page q-pa-md"
    :class="{
      'users-page--roles': tab === 'roles',
      'viewport-page--desktop': tab === 'roles',
      'users-page--privileges': tab === 'privileges',
    }"
    :style-fn="pageStyle"
  >
    <PageHeader :icon="navigationIcon('people')" :title="$t('nav.users')" :description="$t('nav.users_desc')" />

    <q-tabs
      v-if="availableTabs.length"
      v-model="tab"
      active-color="primary"
      indicator-color="primary"
      align="left"
      dense
      outside-arrows
      mobile-arrows
      narrow-indicator
      class="users-tabs text-primary"
    >
      <q-tab v-for="item in availableTabs" :key="item.name" :name="item.name" :label="$t(item.labelKey)" :icon="item.icon" />
    </q-tabs>

    <q-separator v-if="availableTabs.length" />

    <q-tab-panels v-if="availableTabs.length" v-model="tab" animated keep-alive class="users-panels bg-transparent">
      <q-tab-panel v-if="canView('users')" name="users" class="q-pa-none q-pt-md">
        <UserManager :authorization-label="userAuthorizationLabel" @open-authorizations="openAuthorizations" />
      </q-tab-panel>

      <q-tab-panel v-if="canView('teams') && userTeams" name="teams" class="q-pa-none q-pt-md">
        <component :is="userTeams.manager" />
      </q-tab-panel>

      <q-tab-panel v-if="canView('roles')" name="roles" class="roles-panel q-pa-none">
        <RoleManager v-model:selected-role-id="selectedRoleId" />
      </q-tab-panel>

      <q-tab-panel v-if="canView('privileges')" name="privileges" class="privileges-panel q-pa-none">
        <PrivilegeListManager />
      </q-tab-panel>

      <q-tab-panel v-for="item in userViews" :key="item.name" :name="item.name" class="q-pa-none q-pt-md">
        <component :is="item.component" :user-id="authorizationUserId" />
      </q-tab-panel>
    </q-tab-panels>
  </q-page>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { PrivilegeListManager, RoleManager, usePrivilegeStore } from '@/core/authorize'
import { navigationIcon } from '@/core/navigation'
import { PageHeader } from '@/core/util'
import { visibleUserAdministrationTabs } from '../access'
import UserManager from '../components/UserManager.vue'
import { userTabs } from '../userTabs'
import { userTeams } from '../userTeamAccess'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const privilegeStore = usePrivilegeStore()
const standardTabs = computed(() => visibleUserAdministrationTabs(privilegeStore.hasAnyPrivilege))
const canView = (name: string) => standardTabs.value.some(item => item.name === name)
const userViews = computed(() => userTabs.filter(item => !item.formOnly && privilegeStore.hasPrivilege(item.privilege)))
const availableTabs = computed(() => [...standardTabs.value, ...userViews.value])
const tab = computed({
  get: () => availableTabs.value.find(item => item.name === route.query.tab)?.name ?? availableTabs.value[0]?.name ?? '',
  set: (name: string) => {
    if (name === tab.value) return
    void router.replace({ query: { ...route.query, tab: name === 'users' ? undefined : name }, hash: route.hash })
  },
})

const selectedRoleId = ref<number | null>(null)
const authorizationUserId = ref<number>()
const userAuthorizationLabel = computed(() => {
  const view = userViews.value[0]
  return view ? t(view.labelKey) : undefined
})

function openAuthorizations(userId: number) {
  const view = userViews.value[0]
  if (!view) return
  authorizationUserId.value = userId
  tab.value = view.name
}

function pageStyle(offset: number, height: number) {
  return {
    minHeight: `${height - offset}px`,
    '--users-page-height': `${height - offset}px`,
    '--users-layout-offset': `${offset}px`,
  }
}
</script>

<style scoped>
.users-tabs {
  max-width: 100%;
}

.users-page--roles {
  display: flex;
  flex-direction: column;
  height: calc(100dvh - var(--users-layout-offset));
  overflow: hidden;
}

.users-page--roles > :not(.users-panels) {
  flex: none;
}

.users-page--roles .users-panels {
  flex: 1 1 0;
  min-height: 0;
}

.roles-panel {
  height: 100%;
  overflow: hidden;
}

@media (min-width: 1024px) {
  .users-page--privileges {
    display: flex;
    flex-direction: column;
    height: var(--users-page-height);
  }

  .users-page--privileges > * {
    flex-shrink: 0;
  }

  .users-page--privileges .users-panels {
    flex: 1;
    min-height: 0;
  }

  .privileges-panel {
    height: 100%;
    overflow: hidden;
  }
}

@media (max-width: 599px) {
  .users-page {
    padding: 8px;
  }

  .users-tabs :deep(.q-tab) {
    min-width: max-content;
  }
}
</style>
