<template>
    <div v-if="canEdit">
        <q-banner v-if="error" rounded role="alert" class="q-mb-sm">{{ t('messagingProviders.telegram.toolError') }}</q-banner>
        <div v-if="ready" role="status" class="text-body2 q-mb-sm">{{ t('messagingProviders.telegram.toolReady') }}</div>
        <div v-else-if="conflict" role="status" class="text-body2 q-mb-sm">{{ t('messagingProviders.telegram.toolConflict') }}</div>
        <q-btn v-if="!ready && !conflict" color="primary" icon="add" no-caps
            :label="t('messagingProviders.telegram.createTool')" :loading="creating" @click="createTool" />
        <q-btn v-else to="/tools" outline color="primary" icon="settings" no-caps
            :label="t('messagingProviders.telegram.openTools')" />
    </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { useToolStore } from '../stores/toolStore'

const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const toolStore = useToolStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.TOOL_EDIT))
const creating = ref(false)
const error = ref(false)
const ready = ref(false)
const conflict = ref(false)

async function createTool(): Promise<void> {
    if (!canEdit.value || creating.value) return
    creating.value = true
    error.value = false
    try {
        await toolStore.fetchTools()
        const existing = toolStore.tools.find(tool => tool.code === 'telegrem')
        if (existing) {
            const config = existing.messenger_config
            const token = existing.connection_schema?.params.token
            ready.value = config?.service === 'telegram' && config.param_map?.token === 'token'
                && token?.type === 'password' && token.required === true
            conflict.value = !ready.value
            return
        }
        // A privilege change while loading must not trigger a write.
        if (!canEdit.value) return
        await toolStore.createTool({
            code: 'telegrem',
            label: 'Telegram',
            messenger_config: { service: 'telegram', settings: {}, param_map: { token: 'token' } },
            connection_schema: { params: {
                token: { type: 'password', required: true, default: '',
                    label: t('messagingProviders.telegram.tokenLabel'), description: t('messagingProviders.telegram.tokenDescription') },
            } },
        })
        ready.value = true
    } catch {
        error.value = true
    } finally {
        creating.value = false
    }
}
</script>
