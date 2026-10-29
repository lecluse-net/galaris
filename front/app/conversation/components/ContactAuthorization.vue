<template>
  <q-card-section>
    <div class="text-subtitle2">{{ t('conversation.contactAuthorization.title') }}</div>
    <q-banner rounded class="q-my-sm">
      <template #avatar><q-icon :name="authorization.allowed === true ? 'verified_user' : 'pause_circle'" color="primary" /></template>
      {{ t(`conversation.contactAuthorization.${authorization.allowed === true ? 'allowed' : authorization.allowed === false ? 'denied' : authorization.manager_user_id === null ? 'noManager' : 'pending'}`) }}
    </q-banner>
    <q-list dense>
      <q-item v-for="field in fields" :key="field.key">
        <q-item-section>
          <q-item-label caption>{{ t(`conversation.contactAuthorization.fields.${field.key}`) }}</q-item-label>
          <q-item-label class="text-wrap">{{ field.value }}</q-item-label>
        </q-item-section>
      </q-item>
    </q-list>
    <q-btn v-if="canReadPermissions" outline color="primary" icon="approval" class="q-mt-sm"
      :label="t('conversation.contactAuthorization.permissions')" :to="agentId === undefined ? '/permissions' : { path: '/permissions', query: { agent_id: String(agentId) } }" />
  </q-card-section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import type { ContactAuthorizationDetails } from '../types'

const props = defineProps<{ authorization: ContactAuthorizationDetails; agentId?: number }>()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const canReadPermissions = computed(() => [privileges.PERMISSION_ACCESS, privileges.PERMISSION_DECIDE, privileges.PERMISSION_REVOKE]
  .some(privilege => privilegeStore.hasPrivilege(privilege)))
const fields = computed(() => {
  const values: Record<string, string | boolean> = {
    display_name: props.authorization.display_name,
    external_id: props.authorization.external_id,
    ...props.authorization.profile,
  }
  return ['display_name', 'external_id', 'first_name', 'last_name', 'username', 'language_code', 'is_bot', 'is_premium']
    .filter(key => values[key] !== undefined && values[key] !== '')
    .map(key => ({ key, value: typeof values[key] === 'boolean'
      ? t(values[key] ? 'common.yes' : 'common.no') : values[key] }))
})
</script>
