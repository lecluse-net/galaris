<template>
  <q-card class="user-admin-dialog">
    <q-card-section class="galaris-dialog-title row items-center no-wrap">
      <q-icon name="manage_accounts" size="sm" />
      <div class="text-h6 ellipsis q-ml-sm">{{ isEdit ? $t('userAdmin.editTitle') : $t('userAdmin.createTitle') }}</div>
      <q-space />
      <q-btn v-close-popup flat round dense icon="close" :aria-label="$t('common.close')" />
    </q-card-section>

    <q-tabs v-if="user && tabs.length" v-model="tab" align="left" class="text-primary"><q-tab name="account" :label="$t('userAdmin.editTitle')" /><q-tab v-for="item in tabs" :key="item.name" :name="item.name" :label="$t(item.labelKey)" :icon="item.icon" /></q-tabs>
    <q-card-section v-if="user && tab !== 'account'"><component :is="item.component" v-for="item in tabs.filter(x=>x.name===tab)" :key="item.name" :user-id="user.id" /></q-card-section>
    <q-card-section v-show="tab === 'account'" class="q-pt-md">
      <q-form @submit.prevent="onSubmit" class="q-gutter-md">
        <q-input
          v-model="form.email"
          :label="$t('auth.email')"
          type="email"
          outlined
          autofocus
          :rules="[val => !!val || $t('auth.emailRequired')]"
        />

        <q-input
          v-model="form.display_name"
          :label="$t('userAdmin.displayName')"
          outlined
        />

        <q-input
          v-model="form.password"
          :label="$t('auth.password')"
          :type="showPassword ? 'text' : 'password'"
          outlined
          maxlength="72"
          :rules="isEdit ? [val => !val || val.length >= 12 || $t('userAdmin.passwordMin')] : [val => !!val || $t('auth.passwordRequired'), val => val.length >= 12 || $t('userAdmin.passwordMin')]"
          :hint="isEdit ? $t('userAdmin.passwordKeep') : ''"
        >
          <template v-slot:append>
            <q-icon
              :name="showPassword ? 'visibility_off' : 'visibility'"
              class="cursor-pointer"
              @click="showPassword = !showPassword"
            />
          </template>
        </q-input>

        <q-toggle
          v-model="form.is_active"
          :label="$t('userAdmin.accountActive')"
          color="green"
        />

        <div class="user-admin-actions">
          <q-btn :label="$t('common.cancel')" color="primary" flat v-close-popup />
          <q-btn v-if="canSubmit" :label="isEdit ? $t('common.edit') : $t('common.create')" type="submit" color="primary" :loading="loading" />
        </div>
      </q-form>
    </q-card-section>
  </q-card>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, PropType } from 'vue'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { userTabs } from '../userTabs'

const props = defineProps({
  user: {
    type: Object as PropType<any>,
    default: null
  },
  loading: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['submit'])

const privilegeStore = usePrivilegeStore()
const tab=ref('account')
const tabs=computed(()=>userTabs.filter(item=>privilegeStore.hasPrivilege(item.privilege)))
watch(tabs,items=>{if(!items.some(item=>item.name===tab.value))tab.value='account'})
const isEdit = computed(() => !!props.user)
const canSubmit = computed(() => privilegeStore.hasPrivilege(
  isEdit.value ? privileges.UPDATE_USER : privileges.CREATE_USER,
))
const showPassword = ref(false)

const form = reactive({
  email: '',
  display_name: '',
  password: '',
  is_active: true
})

watch(() => props.user, (newUser) => {
  if (newUser) {
    form.email = newUser.email
    form.display_name = newUser.display_name || ''
    form.is_active = newUser.is_active
    form.password = '' 
  } else {
    // Reset for Create mode
    form.email = ''
    form.display_name = ''
    form.password = ''
    form.is_active = true
  }
}, { immediate: true })

function onSubmit() {
  if (!canSubmit.value) return
  const data: any = {
    email: form.email,
    display_name: form.display_name,
    is_active: form.is_active
  }
  if (form.password) {
    data.password = form.password
  }
  emit('submit', data)
}
</script>

<style scoped>
.user-admin-dialog {
  width: 900px;
  max-width: calc(100vw - 32px);
}

.user-admin-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

@media (max-width: 599px) {
  .user-admin-actions {
    display: grid;
    grid-template-columns: 1fr;
  }

  .user-admin-actions .q-btn {
    width: 100%;
  }
}
</style>
