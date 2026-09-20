<template>
  <div class="role-manager q-pa-md">
    <div class="role-manager-actions row justify-end q-mb-md">
      <q-btn v-if="canManage" color="primary" :label="$t('authorize.roles.new')" icon="add" @click="openCreateDialog" />
    </div>

    <!-- Table -->
    <!-- Role List -->
    <q-list bordered class="rounded-borders">
      <div v-if="loading" class="row justify-center q-pa-md">
          <q-spinner color="primary" size="2em" />
      </div>
      
      <q-expansion-item
        v-for="role in roles"
        :key="role.id"
        group="roles"
        icon="security"
        :label="localizedAuthorizeLabel(role)"
        :caption="role.code"
        header-class="text-primary"
        class="role-item"
      >
        <template v-slot:header>
          <q-item-section avatar>
            <q-icon name="security" color="primary" />
          </q-item-section>

          <q-item-section class="min-width-0">
            <q-item-label>{{ localizedAuthorizeLabel(role) }}</q-item-label>
            <q-item-label caption>{{ role.code }}</q-item-label>
          </q-item-section>

          <q-item-section side>
            <div class="role-header-actions">
              <q-btn v-if="canManage" flat round color="primary" icon="edit" size="sm" @click.stop="openEditDialog(role)">
                <q-tooltip>{{ $t('common.edit') }}</q-tooltip>
              </q-btn>
              <q-btn v-if="canManage" flat round color="negative" icon="delete" size="sm" @click.stop="confirmDelete(role)">
                <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
              </q-btn>
            </div>
          </q-item-section>
        </template>

        <q-card>
          <q-card-section>
            <div class="text-subtitle2 q-mb-sm">{{ $t('authorize.roles.associatedPrivileges') }}</div>
            
            <!-- Grouped Display -->
            <div v-if="role.privileges.length > 0">
                <div v-for="(group, listName) in groupPrivileges(role.privileges)" :key="listName" class="q-mb-md">
                    <div class="text-caption text-weight-bold text-primary q-mb-xs">{{ listName }}</div>
                    <div class="role-privilege-list">
                        <q-chip
                            v-for="priv in group"
                            :key="priv.id"
                            :removable="canManage"
                            @remove="removePrivilege(role, priv)"
                            color="primary"
                            text-color="white"
                            icon="vpn_key"
                            size="sm"
                            class="role-privilege-chip"
                        >
                            {{ localizedAuthorizeLabel(priv) }}
                            <q-tooltip>{{ priv.code }}</q-tooltip>
                        </q-chip>
                    </div>
                </div>
            </div>

             <div v-else class="text-grey italic q-pa-sm">
                {{ $t('authorize.roles.noPrivilege') }}
            </div>

            <div class="q-mt-md">
                <q-btn
                    v-if="canManage"
                    outline
                    color="primary"
                    icon="add"
                    :label="$t('authorize.roles.addPrivileges')"
                    size="sm"
                    @click="openPrivilegesDialog(role)"
                />
            </div>
          </q-card-section>
        </q-card>
      </q-expansion-item>
    </q-list>

    <!-- Create/Edit Dialog -->
    <q-dialog v-model="showDialog">
      <q-card class="role-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="security" size="sm" />
          <div class="text-h6 ellipsis q-ml-sm">{{ isEdit ? $t('authorize.roles.edit') : $t('authorize.roles.new') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="$t('common.close')" />
        </q-card-section>

        <q-card-section class="q-pt-md">
          <q-form @submit="saveRole" class="q-gutter-md">
            <q-input
              v-model="editedItem.code"
              :label="$t('authorize.roles.code')"
              :hint="$t('authorize.roles.codeHint')"
              lazy-rules
              :rules="[val => val && val.length > 0 || $t('authorize.roles.codeRequired')]"
              autofocus
            />
            <q-input
              v-model="editedItem.display_name"
              :label="$t('authorize.roles.displayName')"
            />
            <div class="role-dialog-actions q-mt-md">
              <q-btn :label="$t('common.cancel')" color="primary" flat v-close-popup />
              <q-btn v-if="canManage" :label="isEdit ? $t('common.save') : $t('common.create')" type="submit" color="primary" />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- Privileges Dialog -->
    <q-dialog v-model="showPrivilegesDialog">
      <q-card class="role-privileges-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="vpn_key" size="sm" />
          <div class="text-h6 ellipsis q-ml-sm">{{ $t('authorize.roles.privilegesOf', { role: currentRole ? localizedAuthorizeLabel(currentRole) : '' }) }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="$t('common.close')" />
        </q-card-section>

        <q-card-section class="q-pt-md">
            <div v-if="loadingPrivileges" class="row justify-center">
                <q-spinner color="primary" size="2em" />
            </div>
            <div v-else>
                <q-select
                    v-model="selectedPrivileges"
                    class="role-privilege-select"
                    :options="filteredPrivileges"
                    option-value="id"
                    :option-label="localizedAuthorizeLabel"
                    :label="$t('authorize.roles.associatedPrivileges')"
                    multiple
                    use-chips
                    stack-label
                    emit-value
                    map-options
                    use-input
                    input-debounce="0"
                    @filter="filterPrivileges"
                >
                    <template v-slot:option="scope">
                        <template v-if="shouldShowHeader(scope.opt, scope.index)">
                            <q-item-label header class="q-pt-sm text-weight-bold text-primary bg-grey-2">
                                {{ getPrivilegeListName(scope.opt) }}
                            </q-item-label>
                        </template>
                        
                        <q-item v-bind="scope.itemProps">
                            <q-item-section>
                                <q-item-label>{{ localizedAuthorizeLabel(scope.opt) }}</q-item-label>
                                <q-item-label caption v-if="scope.opt.display_name">{{ scope.opt.code }}</q-item-label>
                            </q-item-section>
                        </q-item>
                    </template>
                </q-select>
            </div>
        </q-card-section>
        
        <q-card-section class="role-dialog-actions">
            <q-btn flat :label="$t('common.close')" color="primary" v-close-popup />
            <q-btn v-if="canManage" flat :label="$t('common.save')" color="primary" @click="savePrivileges" />
        </q-card-section>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { computed, ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { authorizeService, type Role, type RoleWithPrivileges, type Privilege, type PrivilegeList } from '../services/authorize.service'
import { usePrivilegeStore } from '../stores/privilegeStore'
import { useAuthorizeStore } from '../stores/authorizeStore'
import { privileges } from '../definitions'
import { localizedAuthorizeLabel } from '../presentation'

const $q = useQuasar()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const authorizeStore = useAuthorizeStore()
const canManage = computed(() => privilegeStore.hasPrivilege(privileges.MANAGE_ROLE))

const roles = ref<RoleWithPrivileges[]>([])
const privilegeLists = ref<PrivilegeList[]>([])
const loading = ref(false)

// Dialog state
const showDialog = ref(false)
const isEdit = ref(false)
const editedItem = ref({
    id: 0,
    code: '',
    display_name: '' as string | undefined
})

// Privileges state
const showPrivilegesDialog = ref(false)
const currentRole = ref<Role | null>(null)

// For the selector we now want grouped options.
// Quasar q-select doesn't support grouping natively in a simple way for multiple selection with chips easily?
// It supports 'optgroup-label' but that's for single select usually or native select.
// For custom UI in q-select, we can just flatten the list but add headers? 
// OR we can perform grouping logic inside the filter/render.
// The requested layout uses one section per list.
// Let's load the lists first.

const allPrivileges = ref<Privilege[]>([])
const filteredPrivileges = ref<Privilege[]>([])
const selectedPrivileges = ref<number[]>([]) 
const loadingPrivileges = ref(false)

// Lifecycle
onMounted(async () => {
  await Promise.all([loadRoles(), loadPrivilegeLists()])
})

async function loadPrivilegeLists() {
    try {
        privilegeLists.value = await authorizeService.listPrivilegeLists()
    } catch (e) {
        console.error("Error loading privilege lists", e)
    }
}

function groupPrivileges(privileges: Privilege[]): Record<string, Privilege[]> {
    const groups: Record<string, Privilege[]> = {}
    
    // We can use the privilege_list_id directly now.
    // However, we need the DISPLAY NAME of the list.
    // We have privilegeLists loaded.
    
    const listMap = new Map<number, string>()
    for (const list of privilegeLists.value) {
        listMap.set(list.id, list.display_name)
    }
    
    for (const p of privileges) {
        let listName = t('authorize.roles.others')
        if (p.privilege_list_id && listMap.has(p.privilege_list_id)) {
            listName = listMap.get(p.privilege_list_id)!
        }
        
        if (!groups[listName]) {
            groups[listName] = []
        }
        groups[listName].push(p)
    }
    
    // Sort keys alphabetically?
    const sortedKeys = Object.keys(groups).sort()
    const sortedGroups: Record<string, Privilege[]> = {}
    for (const key of sortedKeys) {
        sortedGroups[key] = groups[key].sort((a, b) => {
            const nameA = localizedAuthorizeLabel(a)
            const nameB = localizedAuthorizeLabel(b)
            return nameA.localeCompare(nameB)
        })
    }
    
    return sortedGroups
}

// Helper to get list name for a privilege
function getPrivilegeListName(priv: Privilege): string {
    if (priv.privilege_list_id) {
         const list = privilegeLists.value.find(l => l.id === priv.privilege_list_id)
         if (list) return list.display_name
    }
    return t('authorize.roles.others')
}

function shouldShowHeader(opt: Privilege, index: number): boolean {
    if (index === 0) return true
    const prev = filteredPrivileges.value[index - 1]
    return getPrivilegeListName(opt) !== getPrivilegeListName(prev)
}

function filterPrivileges (val: string, update: (fn: () => void) => void) {
  update(() => {
    // 1. Determine available privileges (All - Current Role's)
    let available: Privilege[]
    
    // We need current role privileges. They were fetched in openPrivilegesDialog but not stored in a way accessible here easily 
    // without re-fetching or using the 'filteredPrivileges' initial state?
    // Actually, 'filteredPrivileges' is initialized in openPrivilegesDialog with the correct list (All - Assigned).
    // so we should filter *that* list? No, q-select filter function expects to rebuild the list from source.
    if (!currentRole.value) {
        available = allPrivileges.value
    } else {
        const role = roles.value.find(r => r.id === currentRole.value?.id)
        const currentIds = role ? role.privileges.map(p => p.id) : []
        available = allPrivileges.value.filter(p => !currentIds.includes(p.id))
    }
    
    // 2. Filter by search term
    let filtered = available
    if (val !== '') {
        const needle = val.toLowerCase()
        filtered = available.filter(v =>
            v.code.toLowerCase().indexOf(needle) > -1
            || localizedAuthorizeLabel(v).toLowerCase().indexOf(needle) > -1
        )
    }
    
    // 3. Sort by List Name then Display Name
    filtered.sort((a, b) => {
        const listA = getPrivilegeListName(a)
        const listB = getPrivilegeListName(b)
        if (listA !== listB) return listA.localeCompare(listB)
        
        const nameA = localizedAuthorizeLabel(a)
        const nameB = localizedAuthorizeLabel(b)
        return nameA.localeCompare(nameB)
    })
    
    filteredPrivileges.value = filtered
  })
}

async function loadRoles() {
  loading.value = true
  try {
    roles.value = await authorizeService.listRoles()
  } catch (error) {
    console.error(error)
    $q.notify({
      color: 'negative',
      message: t('authorize.roles.loadError'),
      icon: 'report_problem'
    })
  } finally {
    loading.value = false
  }
}

// Create/Edit Logic
function openCreateDialog() {
  isEdit.value = false
  editedItem.value = { id: 0, code: '', display_name: '' }
  showDialog.value = true
}

function openEditDialog(item: Role) {
  isEdit.value = true
  editedItem.value = { 
      id: item.id, 
      code: item.code, 
      display_name: item.display_name || '' 
  }
  showDialog.value = true
}

async function saveRole() {
  if (!canManage.value) return
  try {
    if (isEdit.value) {
      await authorizeService.updateRole(editedItem.value.id, {
        code: editedItem.value.code,
        display_name: editedItem.value.display_name
      })
      $q.notify({ color: 'positive', message: t('authorize.roles.updated') })
    } else {
      await authorizeService.createRole({
        code: editedItem.value.code,
        display_name: editedItem.value.display_name
      })
      $q.notify({ color: 'positive', message: t('authorize.roles.created') })
    }
    showDialog.value = false
    await loadRoles()
  } catch (error) {
    console.error(error)
    $q.notify({ color: 'negative', message: t('authorize.roles.saveError'), icon: 'report_problem' })
  }
}

function confirmDelete(item: Role) {
  showConfirmationDialog({
    title: t('common.confirm'),
    message: t('authorize.roles.deleteConfirm', { code: item.code }),
    cancel: true
  }).onOk(async () => {
    try {
      await authorizeService.deleteRole(item.id)
      $q.notify({ color: 'positive', message: t('authorize.roles.deleted') })
      await loadRoles()
    } catch (error) {
       console.error(error)
      $q.notify({ color: 'negative', message: t('authorize.roles.deleteError'), icon: 'report_problem' })
    }
  })
}

// Privileges Logic
async function removePrivilege(role: RoleWithPrivileges, privilege: Privilege) {
    if (!canManage.value) return
    if (!role) return

    showConfirmationDialog({
        title: t('authorize.roles.removePrivilegeTitle'),
        message: t('authorize.roles.removePrivilegeConfirm', {
            priv: localizedAuthorizeLabel(privilege),
            role: localizedAuthorizeLabel(role),
        }),
        cancel: true
    }).onOk(async () => {
        try {
            await authorizeService.removePrivilegesFromRole(role.id, [privilege.id])
            $q.notify({ color: 'positive', message: t('authorize.roles.privilegeRemoved') })
            // Refresh roles to update the list
            await loadRoles()
            // Refresh current user privileges if the modified role is the active role
            if (authorizeStore.activeRole?.id === role.id) {
                await privilegeStore.refreshPrivileges()
            }
        } catch (error) {
            console.error(error)
            $q.notify({ color: 'negative', message: t('authorize.roles.privilegeRemoveError'), icon: 'report_problem' })
        }
    })
}

// Dialog Logic
async function openPrivilegesDialog(role: Role) {
    currentRole.value = role
    showPrivilegesDialog.value = true
    loadingPrivileges.value = true
    selectedPrivileges.value = [] // Reset selection for "Add" mode
    
    try {
        // 1. Get all privileges (to populate dropdown)
        if (allPrivileges.value.length === 0) {
            allPrivileges.value = await authorizeService.listPrivileges()
        }
        
        // 2. Get current role privileges to filter them out
        const roleWithPrivs = await authorizeService.getRole(role.id)
        const currentIds = roleWithPrivs.privileges.map(p => p.id)
        
        // Filter: Options = All - Current
        filteredPrivileges.value = allPrivileges.value.filter(p => !currentIds.includes(p.id))
        
    } catch (error) {
        console.error(error)
        $q.notify({ color: 'negative', message: t('authorize.roles.privilegesLoadError') })
    } finally {
        loadingPrivileges.value = false
    }
}

async function savePrivileges() {
    if (!canManage.value) return
    if (!currentRole.value) return
    if (selectedPrivileges.value.length === 0) {
        showPrivilegesDialog.value = false
        return
    }
    
    try {
        await authorizeService.addPrivilegesToRole(currentRole.value.id, selectedPrivileges.value)
        $q.notify({ color: 'positive', message: t('authorize.roles.privilegesAdded') })
        showPrivilegesDialog.value = false
        await loadRoles()
        // Refresh current user privileges if the modified role is the active role
        if (authorizeStore.activeRole?.id === currentRole.value.id) {
            await privilegeStore.refreshPrivileges()
        }
    } catch (error) {
        console.error(error)
        $q.notify({ color: 'negative', message: t('authorize.roles.privilegesAddError') })
    }
}
</script>

<style scoped>
.role-header-actions,
.role-privilege-list,
.role-dialog-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.role-dialog-actions {
  justify-content: flex-end;
}

.role-privilege-chip {
  max-width: 100%;
  height: auto;
  min-height: 24px;
}

.role-privilege-chip :deep(.q-chip__content),
.role-privilege-select :deep(.q-chip__content) {
  min-width: 0;
  white-space: normal;
  overflow-wrap: anywhere;
}

.role-dialog {
  width: 420px;
  max-width: calc(100vw - 32px);
}

.role-privileges-dialog {
  width: 620px;
  max-width: calc(100vw - 32px);
}

.min-width-0 {
  min-width: 0;
}

@media (max-width: 1023px) {
  .role-privilege-list {
    display: grid;
    grid-template-columns: 1fr;
  }

  .role-privilege-chip {
    width: 100%;
    margin: 0;
  }

  .role-privilege-chip :deep(.q-chip__content) {
    justify-content: flex-start;
  }
}

@media (max-width: 599px) {
  .role-manager {
    padding: 8px;
  }

  .role-manager-actions .q-btn,
  .role-dialog-actions .q-btn {
    width: 100%;
  }

  .role-header-actions {
    display: grid;
    grid-template-columns: repeat(2, auto);
    gap: 2px;
  }

  .role-dialog-actions {
    display: grid;
    grid-template-columns: 1fr;
  }
}
</style>
