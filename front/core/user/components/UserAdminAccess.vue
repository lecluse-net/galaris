<template>
  <section v-for="section in sections" :key="section.kind" class="q-mt-lg" :aria-label="section.title">
    <h3 class="text-subtitle1 text-weight-medium q-my-none q-mb-sm">{{ section.title }}</h3>
    <q-linear-progress v-if="section.state.loading" indeterminate />
    <q-banner v-else-if="section.state.loadError" role="alert">
      {{ section.loadError }}
      <template #action>
        <q-btn outline color="primary" :label="t('common.retry')" @click="load(section.kind)" />
      </template>
    </q-banner>
    <template v-else>
      <q-markup-table v-if="section.rows.length" flat bordered dense separator="horizontal" class="user-access-table">
        <thead>
          <tr>
            <th scope="col" class="text-left">{{ section.fieldLabel }}</th>
            <th v-if="section.kind === 'role'" scope="col" class="text-center">
              {{ t('authorize.profile.byDefault') }}
            </th>
            <th v-else scope="col" class="text-center">{{ t('team.manager') }}</th>
            <th v-if="section.writable" scope="col" class="text-right">{{ t('common.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in section.rows" :key="row.id">
            <td class="text-left">{{ row.label }}</td>
            <td v-if="section.kind === 'role'" class="text-center">
              <q-radio
                dense color="primary" :model-value="defaultRoleId" :val="row.id"
                :aria-label="t('userAdmin.defaultRoleFor', { role: row.label })"
                :disable="disabled || section.state.saving"
                @update:model-value="setDefaultRole(row.id)"
              />
            </td>
            <td v-else class="text-center">
              <q-checkbox v-if="canAssignManager || isTeamManager(row.id)"
                dense color="primary" :model-value="isTeamManager(row.id)"
                :aria-label="t('team.managerFor', { name: row.label })"
                :disable="disabled || section.state.saving || !canAssignManager || !eligibleManager || (!!userId && isTeamManager(row.id))"
                @update:model-value="setTeamManager(row)" />
            </td>
            <td v-if="section.writable" class="text-right">
              <q-btn
                flat round dense color="negative" icon="close"
                :aria-label="t(section.removeLabel, { name: row.label })"
                :disable="disabled || section.state.saving || (section.kind === 'team' && !!userId && isTeamManager(row.id))"
                @click="remove(section.kind, row)"
              />
            </td>
          </tr>
        </tbody>
      </q-markup-table>
      <p v-else class="q-mb-none text-body2">{{ section.emptyLabel }}</p>
      <div v-if="section.writable" class="row justify-end q-mt-sm">
        <q-btn
          outline color="primary" size="sm" icon="add" :label="t('common.add')"
          :aria-label="section.addLabel" aria-haspopup="menu" :aria-expanded="section.state.menuOpen"
          :disable="disabled || section.state.saving || !section.options.length"
        >
          <q-menu v-model="section.state.menuOpen" anchor="bottom end" self="top end"
            :transition-duration="0" max-width="calc(100vw - 16px)">
            <q-list dense role="menu" :aria-label="section.addLabel">
              <q-item
                v-for="(option, index) in section.options" :key="option.id"
                clickable role="menuitem" :data-autofocus="index === 0 ? '' : undefined"
                :disable="disabled || section.state.saving" @click="add(section.kind, option)"
              >
                <q-item-section>{{ option.label }}</q-item-section>
              </q-item>
            </q-list>
          </q-menu>
        </q-btn>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { isAxiosError } from 'axios'
import {
  authorizeService, localizedAuthorizeLabel, privileges, useAuthorizeStore, usePrivilegeStore,
  type AssignmentWithRole, type Role,
} from '@/core/authorize'
import { showConfirmationDialog } from '@/core/util'
import { useAuthStore } from '../stores/authStore'
import type { UserAccessDraft } from '../services/authService'
import { userTeams } from '../userTeamAccess'

type AccessKind = 'role' | 'team'
type Option = { id: number; label: string }
type Team = Awaited<ReturnType<NonNullable<typeof userTeams>['list']>>[number]
type AssignedRole = Pick<AssignmentWithRole, 'id' | 'role' | 'is_default'>

const { userId, disabled, eligibleManager, refreshUserList } = defineProps<{
  userId?: number
  disabled: boolean
  eligibleManager: boolean
  refreshUserList?: () => void
}>()
const draft = defineModel<UserAccessDraft>({ required: true })
const { t } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const authStore = useAuthStore()
const authorizeStore = useAuthorizeStore()
const canManageRoles = computed(() => privilegeStore.hasPrivilege(privileges.MANAGE_ASSIGNMENT))
const canReadTeams = computed(() => !!userTeams && privilegeStore.hasPrivilege(privileges.TEAM_ACCESS))
const canManageTeams = computed(() => canReadTeams.value && privilegeStore.hasPrivilege(privileges.TEAM_MEMBERS_EDIT))
const canAssignManager = computed(() => (userId ? canReadTeams.value : canManageTeams.value)
  && privilegeStore.hasPrivilege(privileges.TEAM_EDIT))
const states = reactive<Record<AccessKind, {
  menuOpen: boolean; loading: boolean; loadError: boolean; saving: boolean
}>>({
  role: { menuOpen: false, loading: false, loadError: false, saving: false },
  team: { menuOpen: false, loading: false, loadError: false, saving: false },
})
const roles = ref<Role[]>([])
const teams = ref<Team[]>([])
const assignments = ref<AssignedRole[]>([])
const memberships = ref<Team[]>([])
const roleRows = computed(() => (userId
  ? assignments.value.map(assignment => assignment.role)
  : roles.value.filter(role => draft.value.role_ids.includes(role.id))
).map(roleOption))
const teamRows = computed(() => (userId
  ? memberships.value
  : teams.value.filter(team => draft.value.team_ids.includes(team.id))
).map(teamOption))
const defaultRoleId = computed(() => userId
  ? assignments.value.find(assignment => assignment.is_default)?.role.id ?? null
  : draft.value.default_role_id)

const sections = computed(() => [
  {
    kind: 'role' as const, visible: canManageRoles.value, writable: true, state: states.role,
    title: t('authorize.tabAssignments'), fieldLabel: t('authorize.assignments.colRole'),
    addLabel: t('userAdmin.addAssignment'), emptyLabel: t('userAdmin.noAssignments'),
    removeLabel: 'userAdmin.removeAssignment', loadError: t('authorize.assignments.loadError'),
    rows: roleRows.value, options: roles.value.filter(role => !roleRows.value.some(row => row.id === role.id)).map(roleOption),
  },
  {
    kind: 'team' as const, visible: userId ? canReadTeams.value : canManageTeams.value,
    writable: canManageTeams.value, state: states.team, title: t('team.title'), fieldLabel: t('team.details'),
    addLabel: t('userAdmin.addTeam'), emptyLabel: t('userAdmin.noTeams'),
    removeLabel: 'userAdmin.removeTeam', loadError: t('team.error'),
    rows: teamRows.value, options: teams.value.filter(team => !teamRows.value.some(row => row.id === team.id)).map(teamOption),
  },
].filter(section => section.visible))

watch(canManageRoles, allowed => { if (allowed) void load('role') }, { immediate: true })
watch([canReadTeams, canManageTeams], ([read, write]) => {
  if (userId ? read : write) void load('team')
}, { immediate: true })
watch(() => eligibleManager, eligible => {
  if (!userId && !eligible && draft.value.managed_team_ids.length) {
    draft.value = { ...draft.value, managed_team_ids: [] }
  }
})

function roleOption(role: Role): Option {
  const label = localizedAuthorizeLabel(role)
  return { id: role.id, label: label === role.code ? label : `${label} (${role.code})` }
}

function teamOption(team: Team): Option {
  return { id: team.id, label: team.name }
}

async function load(kind: AccessKind) {
  const state = states[kind]
  state.loading = true
  state.loadError = false
  try {
    if (kind === 'role') {
      const [options, current] = await Promise.all([
        authorizeService.assignmentRoleOptions(), userId ? authorizeService.getUserAssignments(userId) : [],
      ])
      roles.value = options
      assignments.value = current
    } else if (userTeams) {
      const [options, current] = await Promise.all([
        canManageTeams.value ? userTeams.list() : [], userId ? userTeams.list(userId) : [],
      ])
      teams.value = options
      memberships.value = current
    }
  } catch {
    state.loadError = true
  } finally {
    state.loading = false
  }
}

async function change(kind: AccessKind, operation: () => Promise<void>, errorKey: string,
  allowed = kind === 'role' ? canManageRoles.value : canManageTeams.value) {
  const state = states[kind]
  if (!allowed || disabled || state.saving) return
  state.saving = true
  try {
    await operation()
  } catch (error) {
    const detail = isAxiosError<{ detail?: string }>(error) ? error.response?.data?.detail : undefined
    $q.notify({ type: 'negative', message: typeof detail === 'string' ? detail : t(errorKey) })
  } finally {
    state.saving = false
  }
}

function add(kind: AccessKind, selected: Option) {
  states[kind].menuOpen = false
  void change(kind, async () => {
    if (kind === 'role') {
      const role = roles.value.find(option => option.id === selected.id)
      if (!role || roleRows.value.some(row => row.id === role.id)) return
      if (userId) {
        const assignment = await authorizeService.createAssignment({ user_id: userId, role_id: role.id })
        assignments.value.push({ ...assignment, role })
        refreshUserList?.()
      } else {
        draft.value = { ...draft.value, role_ids: [...draft.value.role_ids, role.id] }
      }
    } else if (userTeams) {
      const team = teams.value.find(team => team.id === selected.id)
      if (!team || teamRows.value.some(row => row.id === selected.id)) return
      if (userId) {
        await userTeams.membership(selected.id, userId, true)
        memberships.value.push(team)
        refreshUserList?.()
      } else {
        draft.value = { ...draft.value, team_ids: [...draft.value.team_ids, selected.id] }
      }
    }
  }, kind === 'role' ? 'authorize.assignments.createError' : 'team.error')
}

function remove(kind: AccessKind, row: Option) {
  if (!userId) {
    if (kind === 'role') {
      draft.value = {
        ...draft.value, role_ids: draft.value.role_ids.filter(id => id !== row.id),
        default_role_id: defaultRoleId.value === row.id ? null : defaultRoleId.value,
      }
    } else {
      draft.value = { ...draft.value, team_ids: draft.value.team_ids.filter(id => id !== row.id),
        managed_team_ids: draft.value.managed_team_ids.filter(id => id !== row.id) }
    }
    return
  }
  const currentUserId = userId
  showConfirmationDialog({
    title: t('common.confirm'),
    message: t(kind === 'role' ? 'authorize.assignments.deleteConfirm' : 'userAdmin.removeTeamConfirm', { name: row.label }),
    cancel: true,
  }).onOk(() => change(kind, async () => {
    if (kind === 'role') {
      const assignment = assignments.value.find(item => item.role.id === row.id)
      if (!assignment) return
      await authorizeService.deleteAssignment(assignment.id)
      assignments.value = assignments.value.filter(item => item.id !== assignment.id)
      refreshUserList?.()
    } else if (userTeams) {
      await userTeams.membership(row.id, currentUserId, false)
      memberships.value = memberships.value.filter(item => item.id !== row.id)
      refreshUserList?.()
    }
  }, kind === 'role' ? 'authorize.assignments.deleteError' : 'team.error'))
}

function isTeamManager(teamId: number): boolean {
  return userId ? memberships.value.some(team => team.id === teamId && team.manager_user_id === userId)
    : draft.value.managed_team_ids.includes(teamId)
}

function setTeamManager(row: Option) {
  if (!canAssignManager.value || !eligibleManager || disabled || states.team.saving || !userTeams) return
  const team = (userId ? memberships.value : teams.value).find(team => team.id === row.id)
  if (!team) return
  const service = userTeams
  const assign = () => change('team', async () => {
    if (userId) {
      await service.assignManager(team.id, userId)
      team.manager_user_id = userId
      refreshUserList?.()
    } else {
      const ids = draft.value.managed_team_ids
      draft.value = { ...draft.value, managed_team_ids: ids.includes(team.id)
        ? ids.filter(id => id !== team.id) : [...ids, team.id] }
    }
  }, 'team.saveError', canAssignManager.value)
  if (team.manager_user_id != null && !isTeamManager(team.id)) {
    showConfirmationDialog({ title: t('team.manager'), message: t('team.replaceManager', { name: team.name }), cancel: true })
      .onOk(assign)
  } else {
    void assign()
  }
}

function setDefaultRole(roleId: number) {
  if (!userId) {
    draft.value = { ...draft.value, default_role_id: roleId }
    return
  }
  const target = assignments.value.find(assignment => assignment.role.id === roleId)
  if (!target) return
  void change('role', async () => {
    if (authStore.user?.id === userId) {
      await authorizeStore.setDefaultAssignment(target.id)
    } else {
      await authorizeService.setDefaultAssignment(target.id)
    }
    for (const assignment of assignments.value) assignment.is_default = assignment.id === target.id
  }, 'authorize.profile.updateError')
}
</script>

<style scoped>
.user-access-table td:first-child {
  white-space: normal;
  overflow-wrap: anywhere;
}
</style>
