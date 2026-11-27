<template>
  <div class="role-manager q-pa-md">
    <PanelState v-if="loading" state="loading" />
    <PanelState v-else-if="loadFailed" state="error" :message="t('authorize.roles.loadError')"
      :retry-label="t('common.retry')" @retry="load" />

    <template v-else>
      <div class="role-toolbar">
        <div class="role-buttons" role="group" :aria-label="t('authorize.tabRoles')">
          <q-btn
            v-for="role in roles"
            :key="role.id"
            :label="localizedAuthorizeLabel(role)"
            :outline="role.id !== selectedRole?.id"
            :aria-pressed="role.id === selectedRole?.id"
            color="primary"
            unelevated
            no-caps
            @click="selectedRoleId = role.id"
          />
        </div>

        <q-btn v-if="canManage" color="primary" icon="add" :label="t('authorize.roles.new')"
          :disable="saving" @click="openRoleDialog()" />
      </div>

      <PanelState v-if="!selectedRole" state="empty" :message="t('authorize.roles.noRole')" />
      <template v-else>
        <div class="role-privilege-header q-my-md">
          <h2 id="role-privileges-heading" class="text-h6 q-my-none">{{ t('authorize.roles.privilegesOf', { role: localizedAuthorizeLabel(selectedRole) }) }}</h2>
          <div v-if="canManage" class="row no-wrap">
            <q-btn flat round color="primary" icon="edit" :aria-label="t('authorize.roles.edit')"
              :disable="saving" @click="openRoleDialog(selectedRole)">
              <q-tooltip>{{ t('authorize.roles.edit') }}</q-tooltip>
            </q-btn>
            <q-btn flat round color="negative" icon="delete" :aria-label="t('common.delete')"
              :disable="saving" @click="confirmDelete(selectedRole)">
              <q-tooltip>{{ t('common.delete') }}</q-tooltip>
            </q-btn>
          </div>
        </div>

        <PanelState v-if="!privilegeGroups.length" state="empty" :message="t('authorize.roles.noPrivilege')" />
        <div v-else class="role-privilege-scroll" role="region" aria-labelledby="role-privileges-heading" tabindex="0" :aria-busy="saving">
          <div class="role-privilege-columns">
            <q-card v-for="group in privilegeGroups" :key="group.id ?? 'unclassified'" tag="section" flat bordered class="role-category">
              <h3 class="role-category-title text-subtitle1 text-weight-medium q-my-none q-px-md q-py-sm">{{ group.label }}</h3>
              <q-separator />
              <q-list separator>
                <q-item v-for="privilege in group.privileges" :key="privilege.id" class="role-privilege-item">
                  <q-toggle
                    v-if="!isAdministratorRole"
                    class="role-privilege-toggle"
                    :label="localizedAuthorizeLabel(privilege)"
                    :model-value="selectedPrivilegeIds.has(privilege.id)"
                    :disable="!canManage || saving"
                    color="primary"
                    left-label
                    @update:model-value="togglePrivilege(selectedRole, privilege.id, $event)"
                  />
                  <q-item-section v-else class="role-privilege-text">
                    <q-item-label>{{ localizedAuthorizeLabel(privilege) }}</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card>
          </div>
        </div>
      </template>
    </template>

    <q-dialog v-model="showDialog">
      <q-card class="role-dialog galaris-dialog-card">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="security" size="sm" />
          <div class="text-h6 ellipsis q-ml-sm">{{ editedRoleId === null ? t('authorize.roles.new') : t('authorize.roles.edit') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>

        <q-card-section class="galaris-dialog-body">
          <q-form :id="roleFormId" class="q-gutter-y-md" @submit="saveRole">
            <q-input
              v-model="editedRole.code"
              :label="t('authorize.roles.code')"
              :hint="t('authorize.roles.codeHint')"
              outlined
              dense
              lazy-rules
              :rules="[value => !!value?.trim() || t('authorize.roles.codeRequired')]"
              autofocus
            />
            <q-input v-model="editedRole.display_name" :label="t('authorize.roles.displayName')" outlined dense />
          </q-form>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right" class="galaris-dialog-actions">
          <q-btn v-close-popup outline color="primary" :label="t('common.cancel')" />
          <q-btn v-if="canManage" color="primary" type="submit" :form="roleFormId"
            :label="editedRoleId === null ? t('common.create') : t('common.save')" :loading="saving" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onActivated, onMounted, ref, useId } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail, isCancelledRequest } from '@/core/api'
import { PanelState, showConfirmationDialog } from '@/core/util'
import { privileges } from '../definitions'
import { localizedAuthorizeLabel, localizedPrivilegeListLabel } from '../presentation'
import { authorizeService, type Privilege, type PrivilegeList, type RoleWithPrivileges } from '../services/authorize.service'
import { useAuthorizeStore } from '../stores/authorizeStore'
import { usePrivilegeStore } from '../stores/privilegeStore'

const $q = useQuasar()
const { t, locale } = useI18n()
const roleFormId = useId()
const administratorRoleCode = 'admin'
const selectedRoleId = defineModel<number | null>('selectedRoleId', { required: true })
const privilegeStore = usePrivilegeStore()
const authorizeStore = useAuthorizeStore()
const canManage = computed(() => privilegeStore.hasPrivilege(privileges.MANAGE_ROLE))

const roles = ref<RoleWithPrivileges[]>([])
const privilegeLists = ref<PrivilegeList[]>([])
const allPrivileges = ref<Privilege[]>([])
const loading = ref(false)
const loadFailed = ref(false)
const saving = ref(false)
const selectedRole = computed(() => roles.value.find(role => role.id === selectedRoleId.value) ?? roles.value[0])
const isAdministratorRole = computed(() => selectedRole.value?.code === administratorRoleCode)
const selectedPrivilegeIds = computed(() => new Set(selectedRole.value?.privileges.map(privilege => privilege.id)))

const showDialog = ref(false)
const editedRoleId = ref<number | null>(null)
const editedRole = ref({ code: '', display_name: '' })

const privilegeGroups = computed(() => {
  const groups = new Map(privilegeLists.value.map(list => [
    list.id, { id: list.id, label: localizedPrivilegeListLabel(list), privileges: [] as Privilege[] },
  ]))
  const unclassified = { id: null, label: t('authorize.roles.others'), privileges: [] as Privilege[] }
  for (const privilege of allPrivileges.value) {
    const listId = privilege.privilege_list_id
    const group = listId === null ? unclassified : groups.get(listId) ?? unclassified
    group.privileges.push(privilege)
  }
  const compare = new Intl.Collator(locale.value).compare
  const populatedGroups = [...groups.values()]
    .filter(group => group.privileges.length)
    .sort((a, b) => compare(a.label, b.label))
  const result = unclassified.privileges.length ? [...populatedGroups, unclassified] : populatedGroups
  for (const group of result) {
    group.privileges.sort((a, b) => compare(localizedAuthorizeLabel(a), localizedAuthorizeLabel(b)))
  }
  return result
})

onMounted(load)
onActivated(load)

async function load() {
  if (loading.value || saving.value) return
  loading.value = true
  loadFailed.value = false
  try {
    const [loadedRoles, loadedLists, loadedPrivileges] = await Promise.all([
      authorizeService.listRoles(),
      authorizeService.listPrivilegeLists(),
      authorizeService.listPrivileges(),
    ])
    roles.value = loadedRoles
    privilegeLists.value = loadedLists
    allPrivileges.value = loadedPrivileges
  } catch (error) {
    if (!isCancelledRequest(error)) loadFailed.value = true
  } finally {
    loading.value = false
  }
}

function openRoleDialog(role?: RoleWithPrivileges) {
  editedRoleId.value = role?.id ?? null
  editedRole.value = { code: role?.code ?? '', display_name: role?.display_name ?? '' }
  showDialog.value = true
}

function notifyError(error: unknown, fallback: string) {
  if (!isCancelledRequest(error)) {
    $q.notify({ color: 'negative', message: apiErrorDetail(error) ?? t(fallback) })
  }
}

async function saveRole() {
  if (!canManage.value || saving.value) return
  saving.value = true
  const id = editedRoleId.value
  try {
    if (id === null) {
      const created = await authorizeService.createRole(editedRole.value)
      roles.value.push({ ...created, privileges: [] })
      selectedRoleId.value = created.id
      $q.notify({ color: 'positive', message: t('authorize.roles.created') })
    } else {
      const updated = await authorizeService.updateRole(id, editedRole.value)
      roles.value = roles.value.map(role => role.id === id ? { ...role, ...updated } : role)
      $q.notify({ color: 'positive', message: t('authorize.roles.updated') })
    }
    showDialog.value = false
  } catch (error) {
    notifyError(error, 'authorize.roles.saveError')
  } finally {
    saving.value = false
  }
}

function confirmDelete(role: RoleWithPrivileges) {
  showConfirmationDialog({
    title: t('common.confirm'),
    message: t('authorize.roles.deleteConfirm', { code: role.code }),
    cancel: true,
  }).onOk(async () => {
    if (!canManage.value || saving.value) return
    saving.value = true
    try {
      await authorizeService.deleteRole(role.id)
      roles.value = roles.value.filter(item => item.id !== role.id)
      $q.notify({ color: 'positive', message: t('authorize.roles.deleted') })
    } catch (error) {
      notifyError(error, 'authorize.roles.deleteError')
    } finally {
      saving.value = false
    }
  })
}

async function togglePrivilege(role: RoleWithPrivileges, privilegeId: number, enabled: boolean) {
  if (role.code === administratorRoleCode || !canManage.value || saving.value) return
  saving.value = true
  try {
    const updated = enabled
      ? await authorizeService.addPrivilegesToRole(role.id, [privilegeId])
      : await authorizeService.removePrivilegesFromRole(role.id, [privilegeId])
    roles.value = roles.value.map(item => item.id === role.id ? updated : item)
    if (authorizeStore.activeRole?.id === role.id) await privilegeStore.refreshPrivileges()
  } catch (error) {
    notifyError(error, 'authorize.roles.privilegeSaveError')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.role-manager {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.role-toolbar,
.role-buttons,
.role-privilege-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.role-toolbar,
.role-privilege-header {
  flex: none;
  justify-content: space-between;
}

.role-buttons {
  flex: 1 1 280px;
  min-width: 0;
}

.role-buttons .q-btn,
.role-privilege-header h2,
.role-category-title,
.role-privilege-toggle,
.role-privilege-text {
  max-width: 100%;
  overflow-wrap: anywhere;
}

.role-privilege-scroll {
  flex: 1 1 0;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior-y: contain;
  scrollbar-gutter: stable;
}

.role-category {
  break-inside: avoid;
  margin-bottom: 16px;
}

.role-category-title {
  background: var(--solaire-blue-light);
}

.body--dark .role-category-title {
  background: var(--solaire-blue-dark);
}

.role-privilege-item {
  padding: 0;
}

.role-privilege-toggle {
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 44px;
  justify-content: space-between;
  padding: 2px 8px 2px 16px;
}

.role-privilege-text {
  min-height: 44px;
  padding: 2px 16px;
}

@media (min-width: 1024px) {
  .role-privilege-columns {
    columns: 280px;
    column-gap: 16px;
  }
}

@media (max-width: 599px) {
  .role-manager {
    padding: 8px;
  }
}

.role-dialog {
  width: 420px;
  max-width: calc(100vw - 32px);
}
</style>
