<template>
  <div v-if="authorizeStore.assignments.length > 0">
    <q-item 
        v-for="assignment in authorizeStore.assignments" 
        :key="assignment.id"
        clickable 
        v-close-popup 
        @click="switchRole(assignment.role_id)"
        :active="authorizeStore.activeRole?.id === assignment.role_id"
        active-class="bg-blue-1 text-primary"
    >
        <q-item-section avatar>
            <q-icon name="admin_panel_settings" :color="authorizeStore.activeRole?.id === assignment.role_id ? 'primary' : 'grey-7'" />
        </q-item-section>
        <q-item-section>
            <q-item-label>{{ localizedAuthorizeLabel(assignment.role) }}</q-item-label>
            <q-item-label caption>{{ $t('authorize.codeLabel') }}: {{ assignment.role.code }}</q-item-label>
        </q-item-section>
        <q-item-section side v-if="authorizeStore.activeRole?.id === assignment.role_id">
            <q-icon name="check" color="primary" />
        </q-item-section>
    </q-item>
    <q-separator />
  </div>
</template>

<script setup lang="ts">
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useAuthorizeStore } from '../stores/authorizeStore'
import { localizedAuthorizeLabel } from '../presentation'

const $q = useQuasar()
const { t } = useI18n()
const authorizeStore = useAuthorizeStore()

async function switchRole(roleId: number) {
    if (authorizeStore.activeRole?.id === roleId) return;
    
    try {
        await authorizeStore.switchRole(roleId)
        $q.notify({
            type: 'positive',
            message: t('authorize.roleSwitcher.switched'),
            position: 'top'
        })
    } catch (e) {
        $q.notify({
            type: 'negative',
            message: t('authorize.roleSwitcher.switchError'),
            position: 'top'
        })
    }
}
</script>
