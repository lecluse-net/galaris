<template>
    <div v-if="canEdit">
        <q-banner v-if="error" rounded role="alert" class="q-mb-sm">{{ t('messagingProviders.telegram.toolError') }}</q-banner>
        <div v-if="checking" role="status" class="text-body2 q-mb-sm">{{ t('messagingProviders.telegram.checkingServices') }}</div>
        <div v-else-if="conflict" role="status" class="text-body2 q-mb-sm">{{ t('messagingProviders.telegram.toolConflict') }}</div>
        <q-btn v-if="checked && !telegramTool && !conflict" color="primary" icon="add" no-caps
            :label="t('messagingProviders.telegram.createService')" :loading="creating" @click="createService" />
        <q-btn v-else-if="error && !checking" color="primary" icon="refresh" no-caps
            :label="t('common.retry')" @click="loadTools" />
        <q-btn v-else-if="!checking && (telegramTool || conflict)" to="/services" outline color="primary" icon="settings" no-caps
            :label="t('messagingProviders.telegram.openServices')" />
    </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { useServiceStore } from '../stores/serviceStore'

defineProps<{ settings?: Record<string, string | null> }>()

const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const serviceStore = useServiceStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.SERVICE_EDIT))
const creating = ref(false)
const error = ref(false)
const checked = ref(false)
const checking = ref(false)
const telegramTool = computed(() => serviceStore.services.find(tool => tool.messenger_config?.service === 'telegram'))
const conflict = computed(() => !telegramTool.value && serviceStore.services.some(tool => tool.code === 'telegram'))

async function loadTools(): Promise<boolean> {
    if (!canEdit.value || checking.value) return false
    checking.value = true
    checked.value = false
    error.value = false
    try {
        await serviceStore.fetchServices()
        checked.value = true
        return true
    } catch {
        error.value = true
        return false
    } finally {
        checking.value = false
    }
}

watch(canEdit, allowed => {
    if (allowed) void loadTools()
    else checked.value = false
}, { immediate: true })

async function createService(): Promise<void> {
    if (!canEdit.value || creating.value || checking.value || !checked.value || telegramTool.value || conflict.value) return
    creating.value = true
    error.value = false
    try {
        // Refresh before writing: another Service may have been configured since opening.
        if (!await loadTools() || !canEdit.value || telegramTool.value || conflict.value) return
        await serviceStore.createService({
            code: 'telegram',
            label: 'Telegram',
            messenger_config: { service: 'telegram', settings: {}, param_map: { token: 'token' } },
            connection_schema: { params: {
                token: { type: 'password', required: true, default: '',
                    label: t('messagingProviders.telegram.tokenLabel'), description: t('messagingProviders.telegram.tokenDescription') },
            } },
        })
    } catch {
        error.value = true
    } finally {
        creating.value = false
    }
}
</script>
