<template>
  <q-page class="users-page q-pa-md">
    <PageHeader :icon="navigationIcon('people')" :title="$t('nav.users')" :description="$t('nav.users_desc')" />
    <q-tabs v-model="tab" align="left" class="text-primary"><q-tab name="users" :label="$t('nav.users')" icon="people" /><q-tab v-for="item in tabs" :key="item.name" :name="item.name" :label="$t(item.labelKey)" :icon="item.icon" /></q-tabs>
    <div v-if="tab !== 'users'" class="q-mt-md"><component :is="item.component" v-for="item in tabs.filter(x=>x.name===tab)" :key="item.name" :user-id="authorizationUserId" /></div>
    <div v-show="tab === 'users'">

    <div class="users-page-actions row justify-end q-mb-md">
      <q-btn v-if="canCreate" color="primary" icon="add" :label="$t('usersAdmin.newUser')" @click="openCreateDialog" />
    </div>

    <q-table
      :rows="users"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :filter="filter"
      :grid="$q.screen.lt.md"
      :rows-per-page-options="[10, 20, 50, 100, 500]"
      v-model:pagination="pagination"
      @request="onRequest"
      class="users-table"
    >
      <template v-slot:top-right>
        <q-input v-model="filter" class="users-search" borderless dense debounce="300" :placeholder="$t('common.search')">
          <template v-slot:append>
            <q-icon name="search" />
          </template>
        </q-input>
      </template>

      <template #item="props">
        <div class="users-grid-item">
          <q-card flat bordered class="users-grid-card">
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
            <q-separator />
            <q-card-section class="users-grid-footer q-py-sm">
              <div class="text-caption">
                <div class="text-grey-7">{{ $t('usersAdmin.colCreatedAt') }}</div>
                <div>{{ new Date(props.row.created_at).toLocaleDateString() }}</div>
              </div>
              <div class="row items-center q-gutter-xs">
                <q-btn v-if="tabs.length" flat round color="primary" icon="security" :aria-label="$t(tabs[0].labelKey)" @click="openAuthorizations(props.row.id)" />
                <q-btn v-if="canUpdate" flat round color="primary" icon="edit" size="sm" :aria-label="$t('common.edit')" @click="openEditDialog(props.row)">
                  <q-tooltip>{{ $t('common.edit') }}</q-tooltip>
                </q-btn>
                <q-btn v-if="canDelete" flat round color="negative" icon="delete" size="sm" :aria-label="$t('common.delete')" @click="confirmDelete(props.row)">
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

      <template v-slot:body-cell-actions="props">
        <q-td :props="props" class="q-gutter-sm">
          <q-btn v-if="tabs.length" flat round color="primary" icon="security" :aria-label="$t(tabs[0].labelKey)" @click="openAuthorizations(props.row.id)" />
          <q-btn v-if="canUpdate" flat round color="primary" icon="edit" size="sm" @click="openEditDialog(props.row)">
            <q-tooltip>{{ $t('common.edit') }}</q-tooltip>
          </q-btn>
          <q-btn v-if="canDelete" flat round color="negative" icon="delete" size="sm" @click="confirmDelete(props.row)">
            <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <!-- Dialog Create/Edit -->
    <q-dialog v-model="showDialog">
      <UserAdminForm
        :user="selectedUser"
        :loading="submitting"
        @submit="handleSubmit"
      />
    </q-dialog>
    </div>

  </q-page>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { navigationIcon } from '@/core/navigation'
import { ref, computed, onMounted, watch } from 'vue'
import { useQuasar, QTableColumn, type QTableProps } from 'quasar'
import { useI18n } from 'vue-i18n'
import { PageHeader } from '@/core/util'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { authService, User } from '../services/authService'
import UserAdminForm from '../components/UserAdminForm.vue'
import { userTabs } from '../userTabs'

const $q = useQuasar()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const tab=ref('users')
const authorizationUserId=ref<number>()
const tabs=computed(()=>userTabs.filter(item=>!item.formOnly && privilegeStore.hasPrivilege(item.privilege)))
function openAuthorizations(id:number) { authorizationUserId.value=id; tab.value=tabs.value[0]?.name??'users' }
watch(tabs,items=>{if(tab.value!=='users'&&!items.some(item=>item.name===tab.value))tab.value='users'})
const canCreate = computed(() => privilegeStore.hasPrivilege(privileges.CREATE_USER))
const canUpdate = computed(() => privilegeStore.hasPrivilege(privileges.UPDATE_USER))
const canDelete = computed(() => privilegeStore.hasPrivilege(privileges.DELETE_USER))
const users = ref<User[]>([])
const loading = ref(false)
const submitting = ref(false)
const filter = ref('')
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0, sortBy: 'id', descending: false })
let requestVersion = 0

const showDialog = ref(false)
const selectedUser = ref<User | null>(null)

const columns = computed<QTableColumn[]>(() => [
  { name: 'id', field: 'id', label: 'ID', sortable: true, align: 'left' },
  { name: 'email', field: 'email', label: t('auth.email'), sortable: true, align: 'left' },
  { name: 'display_name', field: 'display_name', label: t('usersAdmin.colName'), sortable: true, align: 'left' },
  { name: 'is_active', field: 'is_active', label: t('usersAdmin.colStatus'), sortable: true, align: 'center' },
  { name: 'created_at', field: 'created_at', label: t('usersAdmin.colCreatedAt'), sortable: true, format: (val) => new Date(val).toLocaleDateString() },
  { name: 'actions', field: 'actions', label: t('common.actions'), align: 'right' }
])

async function fetchUsers() {
  const version = ++requestVersion
  loading.value = true
  try {
    const { page, rowsPerPage, sortBy, descending } = pagination.value
    const result = await authService.getUsers({
      skip: (page - 1) * rowsPerPage, limit: rowsPerPage,
      search: filter.value, sort_by: sortBy || 'id', descending,
    })
    if (version !== requestVersion) return
    users.value = result.items
    pagination.value.rowsNumber = result.total
    if (page > 1 && (page - 1) * rowsPerPage >= result.total) {
      pagination.value.page = Math.max(1, Math.ceil(result.total / rowsPerPage))
      await fetchUsers()
    }
  } catch (err: any) {
    if (version !== requestVersion) return
    $q.notify({
      type: 'negative',
      message: t('usersAdmin.loadError')
    })
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

const onRequest: NonNullable<QTableProps['onRequest']> = (request) => {
  pagination.value = { ...pagination.value, ...request.pagination }
  void fetchUsers()
}

function openCreateDialog() {
  selectedUser.value = null
  showDialog.value = true
}

function openEditDialog(user: User) {
  selectedUser.value = { ...user } // copy to avoid reactive mutation in table
  showDialog.value = true
}

async function handleSubmit(formData: any) {
  submitting.value = true
  try {
    if (selectedUser.value) {
      // Update
      await authService.updateUserAdmin(selectedUser.value.id, formData)
      $q.notify({ type: 'positive', message: t('usersAdmin.updated') })
    } else {
      // Create
      await authService.createUser(formData)
      $q.notify({ type: 'positive', message: t('usersAdmin.created') })
    }
    showDialog.value = false
    fetchUsers()
  } catch (err: any) {
     $q.notify({
      type: 'negative',
      message: err.response?.data?.detail || t('common.anError')
    })
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
      fetchUsers()
    } catch (err: any) {
      $q.notify({
        type: 'negative',
        message: err.response?.data?.detail || t('usersAdmin.deleteError')
      })
    }
  })
}

onMounted(() => {
  fetchUsers()
})
</script>

<style scoped>
.users-grid-item {
  width: 50%;
  padding: 8px;
}

.users-grid-card {
  height: 100%;
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

  .users-search {
    width: 100%;
  }

  .users-table :deep(.q-table__top) {
    align-items: stretch;
  }
}

@media (max-width: 599px) {
  .users-page {
    padding: 8px;
  }

  .users-page-actions .q-btn {
    width: 100%;
  }
}
</style>
