<template>
  <div class="privilege-list-manager q-pa-md">
    <div class="privilege-list-actions row justify-end q-mb-md">
      <q-btn v-if="canManage" color="primary" :label="$t('authorize.privilegeLists.newList')" icon="add" @click="openCreateDialog" />
    </div>

    <!-- Info Banner -->
    <q-banner class="privilege-info-banner bg-blue-1 text-primary q-mb-md rounded-borders">
      <template v-slot:avatar>
        <q-icon name="info" color="primary" />
      </template>
      <div>
         {{ $t('authorize.privilegeLists.infoBanner') }}
      </div>
    </q-banner>

    <!-- Drag and Drop Interface -->
    <div class="row q-col-gutter-md">
        
      <!-- Left Column: Unassigned Privileges -->
      <div class="col-12 col-md-4">
        <q-card class="unassigned-privileges-card column full-height bg-grey-1">
          <q-card-section class="bg-grey-3 q-py-sm row items-center">
             <div class="text-subtitle1 text-weight-bold">{{ $t('authorize.privilegeLists.unassigned') }}</div>
             <q-space />
             <q-badge color="grey-7">{{ unassignedPrivileges.length }}</q-badge>
          </q-card-section>

          <q-card-section 
            class="privilege-drop-zone col q-pa-sm scroll start-drop-zone"
            @dragover.prevent
            @drop="onDropToUnassigned"
          >
             <q-chip
                v-for="priv in unassignedPrivileges"
                :key="priv.id"
                :draggable="canManage"
                @dragstart="onDragStart($event, priv)"
                color="white"
                text-color="grey-9"
                icon="vpn_key"
                class="privilege-chip privilege-chip--unassigned cursor-pointer shadow-1"
             >
                {{ localizedAuthorizeLabel(priv) }}
                <q-tooltip>{{ priv.code }}</q-tooltip>
             </q-chip>
             
             <div v-if="unassignedPrivileges.length === 0" class="full-width text-center text-grey italic q-mt-lg">
                {{ $t('authorize.privilegeLists.noneUnassigned') }}
             </div>
          </q-card-section>
        </q-card>
      </div>

      <!-- Right Column: Lists -->
      <div class="col-12 col-md-8">
        <div class="privilege-lists-title text-subtitle1 q-mb-sm text-grey-8">{{ $t('authorize.privilegeLists.lists') }}</div>
        
        <div v-if="loading" class="row justify-center">
            <q-spinner color="primary" size="2em" />
        </div>

        <div class="row q-col-gutter-md">
            <div class="col-12 col-md-6" v-for="list in privilegeLists" :key="list.id">
                <q-card class="privilege-list-card full-height">
                    <q-card-section class="bg-primary text-white q-py-xs row items-center">
                        <div class="privilege-list-name text-subtitle2">{{ list.display_name }}</div>
                        <q-space />
                        <q-btn v-if="canManage" flat round dense icon="edit" size="sm" @click="openEditDialog(list)" />
                        <q-btn v-if="canManage" flat round dense icon="delete" size="sm" @click="confirmDelete(list)" />
                    </q-card-section>
                    
                    <q-card-section 
                        class="privilege-list-drop-zone q-pa-sm"
                        @dragover.prevent
                        @drop="onDropToList($event, list)"
                    >
                         <div class="privilege-chip-list">
                             <q-chip
                                v-for="priv in list.privileges"
                                :key="priv.id"
                                :draggable="canManage"
                                @dragstart="onDragStart($event, priv, list)"
                                color="primary"
                                text-color="white"
                                icon="lock"
                                size="sm"
                                class="privilege-chip cursor-pointer"
                             >
                                {{ localizedAuthorizeLabel(priv) }}
                             </q-chip>
                         </div>
                         
                         <div v-if="list.privileges.length === 0" class="text-center text-grey-5 italic q-mt-sm">
                            {{ $t('authorize.privilegeLists.dropHere') }}
                         </div>
                    </q-card-section>
                </q-card>
            </div>
        </div>
      </div>
    </div>

    <!-- Create/Edit Dialog (Only for List Name) -->
    <q-dialog v-model="showDialog">
      <q-card class="privilege-list-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="list_alt" size="sm" />
          <div class="text-h6 ellipsis q-ml-sm">{{ isEdit ? $t('authorize.privilegeLists.editList') : $t('authorize.privilegeLists.newListTitle') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="$t('common.close')" />
        </q-card-section>

        <q-card-section class="q-pt-md">
          <q-form @submit="saveList" class="q-gutter-md">
            <q-input
              v-model="editedItem.display_name"
              :label="$t('authorize.privilegeLists.listName')"
              lazy-rules
              :rules="[val => val && val.length > 0 || $t('authorize.privilegeLists.nameRequired')]"
              autofocus
            />
            <div class="privilege-dialog-actions q-mt-md">
              <q-btn :label="$t('common.cancel')" color="primary" flat v-close-popup />
              <q-btn v-if="canManage" :label="isEdit ? $t('common.save') : $t('common.create')" type="submit" color="primary" />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>

  </div>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { ref, computed, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { authorizeService, type Privilege, type PrivilegeList } from '../services/authorize.service'
import { privileges } from '../definitions'
import { usePrivilegeStore } from '../stores/privilegeStore'
import { localizedAuthorizeLabel } from '../presentation'

const $q = useQuasar()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const canManage = computed(() => privilegeStore.hasPrivilege(privileges.MANAGE_PRIVILEGE))

const privilegeLists = ref<PrivilegeList[]>([])
const allPrivileges = ref<Privilege[]>([])
const loading = ref(false)

// Dialog state
const showDialog = ref(false)
const isEdit = ref(false)
const editedItem = ref({
    id: 0,
    display_name: ''
})

// Drag and Drop state
const draggedPrivilege = ref<Privilege | null>(null)
const sourceList = ref<PrivilegeList | null>(null) // null if coming from Unassigned

const unassignedPrivileges = computed(() => {
    return allPrivileges.value.filter(p => !p.privilege_list_id)
})

onMounted(async () => {
  await loadData()
})

async function loadData() {
    loading.value = true
    try {
        const [lists, privileges] = await Promise.all([
            authorizeService.listPrivilegeLists(),
            authorizeService.listPrivileges()
        ])
        
        // Helper sort function
        const sortPrivs = (a: Privilege, b: Privilege) => {
            const nameA = localizedAuthorizeLabel(a)
            const nameB = localizedAuthorizeLabel(b)
            return nameA.localeCompare(nameB)
        }

        // Sort Lists
        lists.sort((a, b) => a.display_name.localeCompare(b.display_name))
        
        // Sort Privileges within Lists
        lists.forEach(l => {
            l.privileges.sort(sortPrivs)
        })

        // Sort All Privileges (affects unassignedPrivileges computed)
        privileges.sort(sortPrivs)

        privilegeLists.value = lists
        allPrivileges.value = privileges
    } catch (e) {
        console.error("Error loading data", e)
        $q.notify({ color: 'negative', message: t('authorize.privilegeLists.loadError') })
    } finally {
        loading.value = false
    }
}

// Drag Handlers
function onDragStart(event: DragEvent, privilege: Privilege, fromList: PrivilegeList | null = null) {
    if (event.dataTransfer) {
        event.dataTransfer.dropEffect = 'move'
        event.dataTransfer.effectAllowed = 'move'
        // We can create a custom drag image if we want
    }
    draggedPrivilege.value = privilege
    sourceList.value = fromList
}

async function onDropToList(_event: DragEvent, targetList: PrivilegeList) {
    if (!canManage.value) return
    if (!draggedPrivilege.value) return
    
    // Optimization: Don't do anything if dropped on same list
    if (sourceList.value?.id === targetList.id) return

    try {
        // Optimistic UI update could go here, but doing simple reload for safety first
        await authorizeService.addPrivilegesToList(targetList.id, [draggedPrivilege.value.id])
        $q.notify({ color: 'positive', message: t('authorize.privilegeLists.assigned'), timeout: 500 })
        await loadData()
    } catch (e) {
        console.error(e)
        $q.notify({ color: 'negative', message: t('authorize.privilegeLists.assignError') })
    } finally {
        draggedPrivilege.value = null
        sourceList.value = null
    }
}

async function onDropToUnassigned(_event: DragEvent) {
    if (!canManage.value) return
    if (!draggedPrivilege.value) return
    
    // If already unassigned, do nothing
    if (!sourceList.value) return

    try {
        await authorizeService.removePrivilegesFromList(sourceList.value.id, [draggedPrivilege.value.id])
         $q.notify({ color: 'positive', message: t('authorize.privilegeLists.removed'), timeout: 500 })
         await loadData()
    } catch (e) {
         console.error(e)
        $q.notify({ color: 'negative', message: t('authorize.privilegeLists.removeError') })
    } finally {
        draggedPrivilege.value = null
        sourceList.value = null
    }
}


// CRUD List Lists
function openCreateDialog() {
  isEdit.value = false
  editedItem.value = { id: 0, display_name: '' }
  showDialog.value = true
}

function openEditDialog(item: PrivilegeList) {
  isEdit.value = true
  editedItem.value = { 
      id: item.id, 
      display_name: item.display_name
  }
  showDialog.value = true
}

async function saveList() {
    if (!canManage.value) return
  try {
    if (isEdit.value) {
      await authorizeService.updatePrivilegeList(editedItem.value.id, {
        display_name: editedItem.value.display_name
      })
      $q.notify({ color: 'positive', message: t('authorize.privilegeLists.updated') })
    } else {
      await authorizeService.createPrivilegeList({
        display_name: editedItem.value.display_name
      })
      $q.notify({ color: 'positive', message: t('authorize.privilegeLists.created') })
    }
    showDialog.value = false
    await loadData()
  } catch (error) {
    console.error(error)
    $q.notify({ color: 'negative', message: t('authorize.privilegeLists.saveError'), icon: 'report_problem' })
  }
}

function confirmDelete(item: PrivilegeList) {
  showConfirmationDialog({
    title: t('common.confirm'),
    message: t('authorize.privilegeLists.deleteConfirm', { name: item.display_name }),
    cancel: true
  }).onOk(async () => {
    try {
      await authorizeService.deletePrivilegeList(item.id)
      $q.notify({ color: 'positive', message: t('authorize.privilegeLists.deleted') })
      await loadData()
    } catch (error) {
       console.error(error)
      $q.notify({ color: 'negative', message: t('authorize.privilegeLists.deleteError'), icon: 'report_problem' })
    }
  })
}

</script>

<style scoped>
.start-drop-zone {
    transition: background-color 0.2s;
}

.unassigned-privileges-card {
    min-height: 500px;
}

.privilege-drop-zone,
.privilege-chip-list {
    display: flex;
    align-content: flex-start;
    flex-wrap: wrap;
    gap: 8px;
}

.privilege-list-drop-zone {
    min-height: 100px;
}

.privilege-chip {
    max-width: 100%;
    height: auto;
    min-height: 26px;
}

.privilege-chip :deep(.q-chip__content) {
    min-width: 0;
    white-space: normal;
    overflow-wrap: anywhere;
}

.privilege-list-name {
    min-width: 0;
    overflow-wrap: anywhere;
}

.privilege-list-dialog {
    width: 420px;
    max-width: calc(100vw - 32px);
}

.privilege-dialog-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    flex-wrap: wrap;
}

body.body--dark .privilege-info-banner {
    color: #90caf9 !important;
    border: 1px solid rgba(144, 202, 249, 0.28);
}

body.body--dark .privilege-info-banner :deep(.q-icon) {
    color: #90caf9 !important;
}

body.body--dark .privilege-chip--unassigned {
    color: #eeeeee !important;
    background: #303030 !important;
    border: 1px solid rgba(255, 255, 255, 0.14);
}

@media (max-width: 1023px) {
    .unassigned-privileges-card {
        min-height: 0;
    }

    .privilege-lists-title {
        margin-top: 12px;
    }

    .privilege-drop-zone,
    .privilege-chip-list {
        display: grid;
        grid-template-columns: 1fr;
    }

    .privilege-chip {
        width: 100%;
        margin: 0;
    }

    .privilege-chip :deep(.q-chip__content) {
        justify-content: flex-start;
    }
}

@media (max-width: 599px) {
    .privilege-list-manager {
        padding: 8px;
    }

    .privilege-list-actions .q-btn,
    .privilege-dialog-actions .q-btn {
        width: 100%;
    }

    .privilege-dialog-actions {
        display: grid;
        grid-template-columns: 1fr;
    }
}
</style>
