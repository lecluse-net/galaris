<template>
  <q-card class="user-admin-dialog galaris-dialog-card">
    <DialogHeader
      icon="manage_accounts"
      :title="$t(isEdit ? 'userAdmin.editTitle' : 'userAdmin.createTitle')"
      :close-label="$t('common.close')"
    />

    <q-card-section class="galaris-dialog-body">
      <q-form :id="accountFormId" class="user-admin-fields" @submit="onSubmit">
        <q-input
          v-model="form.email"
          :label="$t('auth.email')"
          type="email"
          outlined
          dense
          hide-bottom-space
          autofocus
          :rules="[val => !!val || $t('auth.emailRequired')]"
        />

        <q-input
          v-model="form.password"
          :label="$t('auth.password')"
          :type="showPassword ? 'text' : 'password'"
          outlined
          dense
          hide-bottom-space
          maxlength="72"
          :rules="isEdit ? [val => !val || val.length >= 12 || $t('userAdmin.passwordMin')] : [val => !!val || $t('auth.passwordRequired'), val => val.length >= 12 || $t('userAdmin.passwordMin')]"
          :hint="isEdit ? $t('userAdmin.passwordKeep') : undefined"
        >
          <template #append>
            <q-btn
              flat round dense color="primary"
              :icon="showPassword ? 'visibility_off' : 'visibility'"
              :aria-label="$t(showPassword ? 'userAdmin.hidePassword' : 'userAdmin.showPassword')"
              @click="showPassword = !showPassword"
            />
          </template>
        </q-input>

        <q-input
          v-model="form.display_name"
          :label="$t('userAdmin.displayName')"
          outlined
          dense
        />

        <q-toggle
          v-model="form.is_active"
          :label="$t('userAdmin.accountActive')"
          color="solaire-green"
          class="user-admin-active"
        />
      </q-form>

      <template v-for="section in settingsSections" :key="section.name">
        <component v-if="section.formOnly" :is="section.component" embedded
          :user-id="user?.id" :disabled="loading" class="q-mt-sm"
          @draft="setSettings(section.name, $event)" />
        <component v-else-if="user" :is="section.component" :user-id="user.id" class="q-mt-lg" />
      </template>

      <UserAdminAccess v-model="access" :user-id="user?.id" :disabled="loading" :refresh-user-list="refreshUserList" />
    </q-card-section>

    <q-card-actions align="right" class="galaris-dialog-actions q-pa-md">
      <q-btn v-close-popup outline color="primary" :label="$t('common.cancel')" />
      <q-btn
        v-if="canSubmit" color="primary" type="submit" :form="accountFormId"
        :label="$t(isEdit ? 'common.edit' : 'common.create')" :loading="loading"
      />
    </q-card-actions>
  </q-card>
</template>

<script setup lang="ts">
import { ref, reactive, computed, useId } from 'vue'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { DialogHeader } from '@/core/util'
import type { User, UserAccessDraft, UserAdminSubmission } from '../services/authService'
import { userTabs } from '../userTabs'
import UserAdminAccess from './UserAdminAccess.vue'

const { user = null, loading = false, refreshUserList } = defineProps<{
  user?: User | null
  loading?: boolean
  refreshUserList?: () => void
}>()
const emit = defineEmits<{ submit: [submission: UserAdminSubmission] }>()

const privilegeStore = usePrivilegeStore()
const accountFormId = useId()
const settingsSections = computed(() => userTabs.filter(item => privilegeStore.hasPrivilege(item.privilege)))
const isEdit = computed(() => !!user)
const canSubmit = computed(() => privilegeStore.hasPrivilege(
  isEdit.value ? privileges.UPDATE_USER : privileges.CREATE_USER,
))
const showPassword = ref(false)
const form = reactive({
  email: user?.email ?? '',
  display_name: user?.display_name ?? '',
  password: '',
  is_active: user?.is_active ?? true,
})
const access = ref<UserAccessDraft>({ role_ids: [], default_role_id: null, team_ids: [] })
const settings = reactive<Record<string, object>>({})

function setSettings(name: string, value: object | null) {
  if (value === null) delete settings[name]
  else settings[name] = value
}

function onSubmit() {
  if (!canSubmit.value || loading) return
  const changes = Object.fromEntries(settingsSections.value
    .filter(section => section.formOnly && settings[section.name])
    .map(section => [section.name, settings[section.name]]))
  const preferences = Object.keys(changes).length ? { settings: changes } : {}
  if (user) {
    emit('submit', {
      userId: user.id,
      update: { ...form, password: form.password || undefined, ...preferences },
    })
  } else {
    emit('submit', { create: { ...form, ...access.value, ...preferences } })
  }
}
</script>

<style scoped>
.user-admin-dialog {
  width: 900px;
  max-width: calc(100vw - 32px);
}

.user-admin-fields {
  display: grid;
  gap: 8px;
}

.user-admin-active {
  align-self: center;
  justify-self: start;
}

@media (min-width: 1024px) {
  .user-admin-fields {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
