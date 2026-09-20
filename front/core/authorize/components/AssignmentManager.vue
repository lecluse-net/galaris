<template>
  <div class="assignment-manager q-pa-md">
    <div class="assignment-actions row justify-end q-mb-md">
      <q-btn v-if="canManage" color="primary" :label="$t('authorize.assignments.new')" icon="add" @click="openCreateDialog" />
    </div>

    <!-- Table -->
    <q-table
      :rows="assignments"
      :rows-per-page-options="[10, 20, 50, 100, 500]"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :grid="$q.screen.lt.md"
      v-model:pagination="pagination"
      class="assignment-table"
      @request="onRequest"
    >
      <template #item="props">
        <div class="assignment-grid-item">
          <q-card flat bordered class="assignment-grid-card">
            <q-card-section class="q-pb-sm">
              <div class="row items-start no-wrap q-gutter-sm">
                <q-avatar color="primary" text-color="white" icon="person" />
                <div class="col min-width-0">
                  <div class="text-subtitle2 assignment-card-value">{{ getUserLabel(props.row) }}</div>
                  <div class="text-caption text-grey-7">{{ $t('authorize.assignments.colUser') }}</div>
                </div>
                <q-btn v-if="canManage" flat round color="negative" icon="delete" size="sm" :aria-label="$t('common.delete')" @click="confirmDelete(props.row)">
                  <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
                </q-btn>
              </div>
            </q-card-section>
            <q-separator />
            <q-card-section class="q-py-sm">
              <div class="text-caption text-grey-7">{{ $t('authorize.assignments.colRole') }}</div>
              <div class="text-body2 assignment-card-value">{{ getRoleLabel(props.row) }}</div>
            </q-card-section>
          </q-card>
        </div>
      </template>
      <template v-slot:body-cell-user="props">
          <q-td :props="props">
              {{ getUserLabel(props.row) }}
          </q-td>
      </template>

      <template v-slot:body-cell-role="props">
          <q-td :props="props">
              {{ getRoleLabel(props.row) }}
          </q-td>
      </template>

      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn v-if="canManage" flat round color="negative" icon="delete" size="sm" @click="confirmDelete(props.row)">
            <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <!-- Create Dialog -->
    <q-dialog v-model="showDialog">
      <q-card class="assignment-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="person_add" size="sm" />
          <div class="text-h6 ellipsis q-ml-sm">{{ $t('authorize.assignments.new') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="$t('common.close')" />
        </q-card-section>

        <q-card-section class="q-pt-md">
          <q-form @submit="saveAssignment" class="q-gutter-md">
            <!-- User Select -->
            <q-select
                v-model="newItem.user_id"
                :options="userOptions"
                option-value="id"
                option-label="email"
                :label="$t('authorize.assignments.userLabel')"
                emit-value
                map-options
                lazy-rules
                :rules="[val => !!val || $t('authorize.assignments.userRequired')]"
                autofocus
                use-input
                :error="userSearchFailed"
                :error-message="$t('authorize.assignments.loadError')"
                @filter="filterUsers"
                @filter-abort="invalidateUserSearch"
                @popup-hide="invalidateUserSearch"
            >
                <template v-slot:option="scope">
                    <q-item v-bind="scope.itemProps">
                        <q-item-section>
                            <q-item-label>{{ scope.opt.display_name || scope.opt.email }}</q-item-label>
                            <q-item-label caption v-if="scope.opt.display_name">{{ scope.opt.email }}</q-item-label>
                        </q-item-section>
                    </q-item>
                </template>
                <template v-slot:no-option>
                    <q-item>
                        <q-item-section class="text-grey">
                            {{ $t('authorize.assignments.noUser') }}
                        </q-item-section>
                    </q-item>
                </template>
            </q-select>

            <!-- Role Select -->
            <q-select
                v-model="newItem.role_id"
                :options="roleOptions"
                option-value="id"
                option-label="code"
                :label="$t('authorize.assignments.roleLabel')"
                emit-value
                map-options
                lazy-rules
                :rules="[val => !!val || $t('authorize.assignments.roleRequired')]"
                use-input
                @filter="filterRoles"
            >
                <template v-slot:option="scope">
                    <q-item v-bind="scope.itemProps">
                        <q-item-section>
                            <q-item-label>{{ localizedAuthorizeLabel(scope.opt) }}</q-item-label>
                            <q-item-label caption v-if="scope.opt.display_name">{{ scope.opt.code }}</q-item-label>
                        </q-item-section>
                    </q-item>
                </template>
                 <template v-slot:selected-item="scope">
                    {{ roleOptionLabel(scope.opt) }}
                </template>
                <template v-slot:no-option>
                    <q-item>
                        <q-item-section class="text-grey">
                            {{ $t('authorize.assignments.noRole') }}
                        </q-item-section>
                    </q-item>
                </template>
            </q-select>

            <div class="assignment-dialog-actions q-mt-md">
              <q-btn :label="$t('common.cancel')" color="primary" flat v-close-popup />
              <q-btn v-if="canManage" :label="$t('common.create')" type="submit" color="primary" />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { ref, computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { isCancelledRequest } from '@/core/api'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { authorizeService, type AssignmentWithRole, type Role } from '../services/authorize.service'
import { userService } from '@/core/user/services/userService'
import type { User } from '@/core/user/services/authService'
import { privileges } from '../definitions'
import { usePrivilegeStore } from '../stores/privilegeStore'
import { localizedAuthorizeLabel } from '../presentation'

const $q = useQuasar()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const canManage = computed(() => privilegeStore.hasPrivilege(privileges.MANAGE_ASSIGNMENT))

const assignments = ref<AssignmentWithRole[]>([])
const loading = ref(false)
const pagination = ref({
  page: 1,
  rowsPerPage: 50,
  rowsNumber: 0 // server-side count
})

// Data for dropdowns
// const users = ref<User[]>([]) // We don't load all users anymore
const roles = ref<Role[]>([])

// Filtered options for dropdowns
const userOptions = ref<User[]>([])
const userSearchFailed = ref(false)
let userSearchVersion = 0
function invalidateUserSearch(): void { userSearchVersion += 1 }
onBeforeUnmount(invalidateUserSearch)
const roleOptions = ref<Role[]>([])

const columns = computed<any[]>(() => [
  { name: 'user', label: t('authorize.assignments.colUser'), field: 'user', sortable: false, align: 'left', format: (_val: any, row: any) => getUserLabel(row) },
  { name: 'role', label: t('authorize.assignments.colRole'), field: 'role', sortable: false, align: 'left' },
  { name: 'actions', label: t('common.actions'), field: 'actions', align: 'right' }
])

const showDialog = ref(false)
watch(showDialog, () => {
  invalidateUserSearch()
  userSearchFailed.value = false
}, { flush: 'sync' })
const newItem = ref({
    user_id: null as number | null,
    role_id: null as number | null
})

onMounted(async () => {
    // Initial load via onRequest
    onRequest({
        pagination: pagination.value
    })
    // Load roles for dropdown
    roles.value = (await authorizeService.listRoles()).map(r => r as unknown as Role)
})

async function onRequest(props: any) {
  const { page, rowsPerPage } = props.pagination
  loading.value = true

  try {
      const resp = await authorizeService.listAssignments(page, rowsPerPage)
      
      assignments.value = resp.items
      
      // Update local pagination object
      pagination.value.page = page
      pagination.value.rowsPerPage = rowsPerPage
      pagination.value.rowsNumber = resp.total
      
  } catch (error) {
    console.error(error)
    $q.notify({
      color: 'negative',
      message: t('authorize.assignments.loadError'),
      icon: 'report_problem'
    })
  } finally {
    loading.value = false
  }
}

async function filterUsers (val: string, update: (callback: () => void) => void, abort: () => void) {
  const version = ++userSearchVersion
  userSearchFailed.value = false
  if (val === '') {
    update(() => {
      userOptions.value = []
    })
    return
  }

  try {
    const users = await userService.listUsers(val)
    if (version !== userSearchVersion) return
    update(() => { userOptions.value = users })
  } catch (error) {
    if (version !== userSearchVersion) return
    userSearchFailed.value = !isCancelledRequest(error)
    abort()
  }
}

function filterRoles (val: string, update: (callback: () => void) => void) {
  if (val === '') {
    update(() => {
      roleOptions.value = roles.value
    })
    return
  }

  update(() => {
    const needle = val.toLowerCase()
    roleOptions.value = roles.value.filter(v => {
        const code = v.code.toLowerCase()
        const name = localizedAuthorizeLabel(v).toLowerCase()
        return code.indexOf(needle) > -1 || name.indexOf(needle) > -1
    })
  })
}

function getUserLabel(row: AssignmentWithRole): string {
    const user = row.user
    if (!user) return `ID: ${row.user_id}`
    if (user.display_name) {
        return `${user.display_name} (${user.email})`
    }
    return user.email
}

function getRoleLabel(row: AssignmentWithRole): string {
    if (!row.role) return '—'
    return roleOptionLabel(row.role)
}

function roleOptionLabel(role: Role): string {
    const label = localizedAuthorizeLabel(role)
    return label === role.code ? role.code : `${label} (${role.code})`
}

function openCreateDialog() {
    newItem.value = { user_id: null, role_id: null }
    // Reset options
    userOptions.value = []
    roleOptions.value = roles.value
    showDialog.value = true
}

async function saveAssignment() {
  if (!canManage.value) return
    if (!newItem.value.user_id || !newItem.value.role_id) return
    
    try {
        await authorizeService.createAssignment({
            user_id: newItem.value.user_id,
            role_id: newItem.value.role_id
        })
        $q.notify({ color: 'positive', message: t('authorize.assignments.created') })
        showDialog.value = false
        // Refresh list
        onRequest({ pagination: pagination.value })
    } catch (error: any) {
        console.error(error)
        let msg = t('authorize.assignments.createError')
        if (error.response?.status === 400) {
            msg = error.response.data.detail || msg
        }
        $q.notify({ color: 'negative', message: msg, icon: 'report_problem' })
    }
}

function confirmDelete(item: AssignmentWithRole) {
  showConfirmationDialog({
    title: t('common.confirm'),
    message: t('authorize.assignments.deleteConfirm'),
    cancel: true
  }).onOk(async () => {
    try {
      await authorizeService.deleteAssignment(item.id)
      $q.notify({ color: 'positive', message: t('authorize.assignments.deleted') })
      // Refresh list
      onRequest({ pagination: pagination.value })
    } catch (error) {
       console.error(error)
      $q.notify({ color: 'negative', message: t('authorize.assignments.deleteError'), icon: 'report_problem' })
    }
  })
}
</script>

<style scoped>
.assignment-grid-item {
  width: 50%;
  padding: 8px;
}

.assignment-grid-card {
  height: 100%;
}

.assignment-card-value {
  overflow-wrap: anywhere;
}

.assignment-dialog {
  width: 480px;
  max-width: calc(100vw - 32px);
}

.assignment-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.min-width-0 {
  min-width: 0;
}

@media (max-width: 1023px) {
  .assignment-grid-item {
    width: 100%;
    padding: 6px 0;
  }
}

@media (max-width: 599px) {
  .assignment-manager {
    padding: 8px;
  }

  .assignment-actions .q-btn {
    width: 100%;
  }

  .assignment-dialog-actions {
    display: grid;
    grid-template-columns: 1fr;
  }

  .assignment-dialog-actions .q-btn {
    width: 100%;
  }
}
</style>
