<template>
  <div>
    <div class="users-page-actions row justify-end q-mb-md">
      <q-btn v-if="canCreate" color="primary" icon="add" :label="$t('usersAdmin.newUser')" @click="openCreateDialog" />
    </div>

    <q-table
      :rows="users"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :grid="$q.screen.lt.md"
      :rows-per-page-options="[10, 20, 50, 100, 500]"
      v-model:pagination="pagination"
      @request="onRequest"
      :onRowClick="canUpdate ? onRowClick : undefined"
      class="users-table"
    >
      <template #top>
        <div class="users-filters">
          <q-input v-model="search" class="users-search" outlined dense clearable debounce="300" maxlength="200" :label="$t('common.search')">
            <template #append><q-icon name="search" /></template>
          </q-input>
          <q-select v-if="canReadAssignments" v-model="roleFilter" class="users-filter" :options="roleOptions"
            :label="$t('authorize.assignments.colRole')" :loading="loadingOptions" outlined dense clearable emit-value map-options />
          <q-select v-if="canReadTeams" v-model="teamFilter" class="users-filter" :options="teamOptions"
            :label="$t('usersAdmin.filterTeam')" :loading="loadingOptions" outlined dense clearable emit-value map-options />
          <q-select v-model="statusFilter" class="users-filter" :options="statusOptions"
            :label="$t('usersAdmin.colStatus')" outlined dense clearable emit-value map-options />
        </div>
      </template>

      <template #item="props">
        <div class="users-grid-item">
          <q-card flat bordered class="users-grid-card" :class="{ 'cursor-pointer': canUpdate }" @click="openEditDialog(props.row)">
            <q-card-section class="q-pb-sm">
              <div class="row items-center no-wrap q-gutter-sm">
                <q-avatar color="primary" text-color="white" icon="person" />
                <div class="col min-width-0">
                  <div class="text-subtitle2 ellipsis">{{ props.row.display_name || props.row.email }}</div>
                  <div class="text-caption text-grey-7 ellipsis">{{ props.row.email }}</div>
                  <div class="text-caption text-grey-7">#{{ props.row.id }}</div>
                </div>
                <q-chip :color="props.row.is_active ? 'positive' : 'negative'" text-color="white" size="sm">
                  {{ props.row.is_active ? $t('user.active') : $t('user.inactive') }}
                </q-chip>
              </div>
            </q-card-section>
            <template v-if="accessColumns.length">
              <q-separator />
              <q-card-section class="column q-gutter-sm q-py-sm">
                <div v-for="column in accessColumns" :key="column.name">
                  <div class="text-caption">{{ column.label }}</div>
                  <UserMembershipLabels :labels="column.field(props.row)" :empty-label="column.emptyLabel" />
                </div>
              </q-card-section>
            </template>
            <q-separator />
            <q-card-section class="users-grid-footer q-py-sm">
              <div class="text-caption">
                <div class="text-grey-7">{{ $t('usersAdmin.colCreatedAt') }}</div>
                <div>{{ new Date(props.row.created_at).toLocaleDateString(locale) }}</div>
              </div>
              <div class="row items-center q-gutter-xs">
                <q-btn v-if="authorizationLabel" flat round color="primary" icon="security" :aria-label="authorizationLabel" @click.stop="emit('openAuthorizations', props.row.id)" />
                <q-btn v-if="canUpdate" flat round color="primary" icon="edit" size="sm" :aria-label="$t('common.edit')" @click.stop="openEditDialog(props.row)">
                  <q-tooltip>{{ $t('common.edit') }}</q-tooltip>
                </q-btn>
                <q-btn v-if="canDelete" flat round color="negative" icon="delete" size="sm" :aria-label="$t('common.delete')" @click.stop="confirmDelete(props.row)">
                  <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
                </q-btn>
              </div>
            </q-card-section>
          </q-card>
        </div>
      </template>

      <template v-slot:body-cell-is_active="props">
        <q-td :props="props">
          <q-chip
            :color="props.value ? 'positive' : 'negative'"
            text-color="white"
            size="sm"
          >
            {{ props.value ? $t('user.active') : $t('user.inactive') }}
          </q-chip>
        </q-td>
      </template>

      <template v-for="column in accessColumns" :key="column.name" #[`body-cell-${column.name}`]="props">
        <q-td :props="props" class="users-access-cell">
          <UserMembershipLabels :labels="props.value" :empty-label="column.emptyLabel" />
        </q-td>
      </template>

      <template v-slot:body-cell-actions="props">
        <q-td :props="props" class="q-gutter-sm">
          <q-btn v-if="authorizationLabel" flat round color="primary" icon="security" :aria-label="authorizationLabel" @click.stop="emit('openAuthorizations', props.row.id)" />
          <q-btn :aria-label="$t('common.edit')" v-if="canUpdate" flat round color="primary" icon="edit" size="sm" @click.stop="openEditDialog(props.row)">
            <q-tooltip>{{ $t('common.edit') }}</q-tooltip>
          </q-btn>
          <q-btn :aria-label="$t('common.delete')" v-if="canDelete" flat round color="negative" icon="delete" size="sm" @click.stop="confirmDelete(props.row)">
            <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <!-- Dialog Create/Edit -->
    <q-dialog v-model="showDialog">
      <UserAdminForm
        :key="dialogVersion"
        :user="selectedUser"
        :loading="submitting"
        :refresh-user-list="fetchUsers"
        @submit="handleSubmit"
      />
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { ref, computed, onActivated, watch } from 'vue'
import { useQuasar, QTableColumn, type QTableProps } from 'quasar'
import { useI18n } from 'vue-i18n'
import { isAxiosError } from 'axios'
import { isCancelledRequest } from '@/core/api'
import { authorizeService, localizedAuthorizeLabel, privileges, usePrivilegeStore, type Role } from '@/core/authorize'
import { authService, type User, type UserAdminSubmission, type UserListEntry } from '../services/authService'
import UserAdminForm from './UserAdminForm.vue'
import UserMembershipLabels from './UserMembershipLabels.vue'
import { userTeams } from '../userTeamAccess'

const $q = useQuasar()
const { t, locale } = useI18n()
const privilegeStore = usePrivilegeStore()
defineProps<{ authorizationLabel?: string }>()
const emit = defineEmits<{ openAuthorizations: [userId: number] }>()
const canCreate = computed(() => privilegeStore.hasPrivilege(privileges.CREATE_USER))
const canUpdate = computed(() => privilegeStore.hasPrivilege(privileges.UPDATE_USER))
const canDelete = computed(() => privilegeStore.hasPrivilege(privileges.DELETE_USER))
const canReadAssignments = computed(() => privilegeStore.hasAnyPrivilege([
  privileges.READ_ASSIGNMENT, privileges.MANAGE_ASSIGNMENT,
]))
const canReadTeams = computed(() => !!userTeams && privilegeStore.hasPrivilege(privileges.TEAM_ACCESS))
const users = ref<UserListEntry[]>([])
const loading = ref(false)
const submitting = ref(false)
const search = ref<string | null>('')
const roleFilter = ref<number | null>(null)
const teamFilter = ref<number | null>(null)
const statusFilter = ref<boolean | null>(null)
const roles = ref<Role[]>([])
const teams = ref<{ id: number; name: string }[]>([])
const loadingOptions = ref(false)
const roleOptions = computed(() => roles.value.map(role => ({ value: role.id, label: localizedAuthorizeLabel(role) })))
const teamOptions = computed(() => teams.value.map(team => ({ value: team.id, label: team.name })))
const statusOptions = computed(() => [
  { value: true, label: t('user.active') },
  { value: false, label: t('user.inactive') },
])
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0, sortBy: 'id', descending: false })
let requestVersion = 0
let optionsVersion = 0

const showDialog = ref(false)
const dialogVersion = ref(0)
const selectedUser = ref<User | null>(null)

const accessColumns = computed(() => [
  {
    name: 'assignments',
    label: t('authorize.tabAssignments'),
    emptyLabel: t('userAdmin.noAssignments'),
    field: (user: UserListEntry) => user.assignments?.map(role => ({
      id: role.id, label: localizedAuthorizeLabel(role),
    })),
    visible: canReadAssignments.value,
  },
  {
    name: 'teams',
    label: t('team.title'),
    emptyLabel: t('userAdmin.noTeams'),
    field: (user: UserListEntry) => user.teams?.map(team => ({ id: team.id, label: team.name })),
    visible: canReadTeams.value,
  },
].filter(column => column.visible))

const columns = computed<QTableColumn[]>(() => [
  { name: 'id', field: 'id', label: 'ID', sortable: true, align: 'left' },
  { name: 'email', field: 'email', label: t('auth.email'), sortable: true, align: 'left' },
  { name: 'display_name', field: 'display_name', label: t('usersAdmin.colName'), sortable: true, align: 'left' },
  ...accessColumns.value.map(column => ({ ...column, align: 'left' as const })),
  { name: 'is_active', field: 'is_active', label: t('usersAdmin.colStatus'), sortable: true, align: 'center' },
  { name: 'created_at', field: 'created_at', label: t('usersAdmin.colCreatedAt'), sortable: true, format: (val) => new Date(val).toLocaleDateString(locale.value) },
  { name: 'actions', field: 'actions', label: t('common.actions'), align: 'right' }
])

async function fetchUsers() {
  const version = ++requestVersion
  loading.value = true
  try {
    const { page, rowsPerPage, sortBy, descending } = pagination.value
    const result = await authService.getUsers({
      skip: (page - 1) * rowsPerPage, limit: rowsPerPage,
      search: search.value?.trim() || undefined, sort_by: sortBy || 'id', descending,
      role_id: canReadAssignments.value ? roleFilter.value ?? undefined : undefined,
      team_id: canReadTeams.value ? teamFilter.value ?? undefined : undefined,
      is_active: statusFilter.value ?? undefined,
      include_access: canReadAssignments.value || canReadTeams.value,
    })
    if (version !== requestVersion) return
    users.value = result.items
    pagination.value.rowsNumber = result.total
    if (page > 1 && (page - 1) * rowsPerPage >= result.total) {
      pagination.value.page = Math.max(1, Math.ceil(result.total / rowsPerPage))
      await fetchUsers()
    }
  } catch (error) {
    if (version !== requestVersion || isCancelledRequest(error)) return
    $q.notify({
      type: 'negative',
      message: t('usersAdmin.loadError')
    })
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

async function loadFilterOptions() {
  const version = ++optionsVersion
  loadingOptions.value = true
  const [roleResult, teamResult] = await Promise.allSettled([
    canReadAssignments.value ? authorizeService.assignmentRoleOptions() : [],
    canReadTeams.value && userTeams ? userTeams.list() : [],
  ])
  if (version !== optionsVersion) return
  loadingOptions.value = false
  if (roleResult.status === 'fulfilled') {
    roles.value = roleResult.value
    if (roleFilter.value !== null && !roles.value.some(role => role.id === roleFilter.value)) roleFilter.value = null
  }
  if (teamResult.status === 'fulfilled') {
    teams.value = teamResult.value
    if (teamFilter.value !== null && !teams.value.some(team => team.id === teamFilter.value)) teamFilter.value = null
  }
  if ([roleResult, teamResult].some(result => result.status === 'rejected' && !isCancelledRequest(result.reason))) {
    $q.notify({
      type: 'negative',
      message: t('usersAdmin.filterLoadError'),
      actions: [{ label: t('common.retry'), handler: () => void loadFilterOptions() }],
    })
  }
}

const onRequest: NonNullable<QTableProps['onRequest']> = (request) => {
  pagination.value = { ...pagination.value, ...request.pagination }
  void fetchUsers()
}

const onRowClick: NonNullable<QTableProps['onRowClick']> = (_event, user: User) => openEditDialog(user)

function openCreateDialog() {
  dialogVersion.value++
  selectedUser.value = null
  showDialog.value = true
}

function openEditDialog(user: User) {
  if (!canUpdate.value) return
  dialogVersion.value++
  selectedUser.value = { ...user } // copy to avoid reactive mutation in table
  showDialog.value = true
}

async function handleSubmit(submission: UserAdminSubmission) {
  if (submitting.value) return
  const version = dialogVersion.value
  submitting.value = true
  try {
    if ('update' in submission) {
      await authService.updateUserAdmin(submission.userId, submission.update)
      $q.notify({ type: 'positive', message: t('usersAdmin.updated') })
    } else {
      await authService.createUser(submission.create)
      $q.notify({ type: 'positive', message: t('usersAdmin.created') })
    }
    if (version === dialogVersion.value) showDialog.value = false
    await fetchUsers()
  } catch (error) {
    const detail = isAxiosError<{ detail?: string }>(error) ? error.response?.data?.detail : undefined
    $q.notify({ type: 'negative', message: typeof detail === 'string' ? detail : t('common.anError') })
  } finally {
    submitting.value = false
  }
}

function confirmDelete(user: User) {
  showConfirmationDialog({
    title: t('common.deleteConfirmTitle'),
    message: t('usersAdmin.deleteConfirm', { email: user.email }),
    cancel: true,
    ok: { label: t('common.delete'), color: 'negative', flat: true }
  }).onOk(async () => {
    try {
      await authService.deleteUser(user.id)
      $q.notify({ type: 'positive', message: t('usersAdmin.deleted') })
      await fetchUsers()
    } catch (err: any) {
      $q.notify({
        type: 'negative',
        message: err.response?.data?.detail || t('usersAdmin.deleteError')
      })
    }
  })
}

watch([search, roleFilter, teamFilter, statusFilter, canReadAssignments, canReadTeams], () => {
  pagination.value.page = 1
  void fetchUsers()
})

onActivated(() => {
  void fetchUsers()
  void loadFilterOptions()
})
watch([canReadAssignments, canReadTeams], loadFilterOptions)
</script>

<style scoped>
.users-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  width: 100%;
}

.users-search {
  flex: 2 1 220px;
}

.users-filter {
  flex: 1 1 150px;
  min-width: 0;
}

.users-grid-item {
  width: 50%;
  padding: 8px;
}

.users-grid-card {
  height: 100%;
}

.users-access-cell {
  max-width: 32ch;
  white-space: normal;
}

.users-grid-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.min-width-0 {
  min-width: 0;
}

@media (max-width: 1023px) {
  .users-grid-item {
    width: 100%;
    padding: 6px 0;
  }

  .users-table :deep(.q-table__top) {
    align-items: stretch;
  }
}

@media (max-width: 599px) {
  .users-filters {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .users-search {
    grid-column: 1 / -1;
  }

  .users-page-actions .q-btn {
    width: 100%;
  }
}
</style>
