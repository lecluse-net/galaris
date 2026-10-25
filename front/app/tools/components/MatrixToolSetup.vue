<template>
    <div v-if="canEdit">
        <q-banner v-if="error" rounded role="alert" class="q-mb-sm">{{ t('messagingProviders.matrix.toolError') }}</q-banner>
        <div v-if="checking" role="status" class="text-body2 q-mb-sm">{{ t('messagingProviders.matrix.checkingTools') }}</div>
        <div v-else-if="conflict" role="status" class="text-body2 q-mb-sm">{{ t('messagingProviders.matrix.toolConflict') }}</div>
        <div v-else-if="checked && !matrixTool && !homeserver" role="status" class="text-body2 q-mb-sm">{{ t('messagingProviders.matrix.homeserverRequired') }}</div>
        <q-btn v-if="checked && !matrixTool && !conflict" color="primary" icon="add" no-caps
            :label="t('messagingProviders.matrix.createTool')" :loading="creating" :disable="!homeserver" @click="createTool" />
        <q-btn v-else-if="error && !checking" color="primary" icon="refresh" no-caps
            :label="t('common.retry')" @click="loadTools" />
        <q-btn v-else-if="!checking && (matrixTool || conflict)" to="/tools" outline color="primary" icon="settings" no-caps
            :label="t('messagingProviders.matrix.openTools')" />
    </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { useToolStore } from '../stores/toolStore'

const props = defineProps<{ settings?: Record<string, string | null> }>()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const toolStore = useToolStore()
const homeserver = computed(() => props.settings?.MESSENGER_MATRIX_HOMESERVER?.trim() ?? '')
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.TOOL_EDIT))
const creating = ref(false)
const error = ref(false)
const checked = ref(false)
const checking = ref(false)
const matrixTool = computed(() => toolStore.tools.find(tool => tool.messenger_config?.service === 'matrix'))
const conflict = computed(() => !matrixTool.value && toolStore.tools.some(tool => tool.code === 'matrix'))

async function loadTools(): Promise<boolean> {
    if (!canEdit.value || checking.value) return false
    checking.value = true
    checked.value = false
    error.value = false
    try {
        await toolStore.fetchTools()
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

async function createTool(): Promise<void> {
    if (!canEdit.value || creating.value || checking.value || !checked.value || !homeserver.value || matrixTool.value || conflict.value) return
    creating.value = true
    error.value = false
    try {
        // Refresh before writing: another Tool may have been configured since opening.
        if (!await loadTools() || !canEdit.value || !homeserver.value || matrixTool.value || conflict.value) return
        await toolStore.createTool({
            code: 'matrix',
            label: 'Matrix',
            messenger_config: {
                service: 'matrix',
                settings: { homeserver: homeserver.value },
                param_map: { user_id: 'user_id', token: 'token', password: 'password' },
            },
            connection_schema: { params: {
                user_id: { type: 'string', required: true, default: '',
                    label: t('messagingProviders.matrix.userIdLabel'), description: t('messagingProviders.matrix.userIdDescription') },
                token: { type: 'password', required: false, default: '',
                    label: t('messagingProviders.matrix.tokenLabel'), description: t('messagingProviders.matrix.tokenDescription') },
                password: { type: 'password', required: false, default: '',
                    label: t('messagingProviders.matrix.passwordLabel'), description: t('messagingProviders.matrix.passwordDescription') },
            } },
        })
    } catch {
        error.value = true
    } finally {
        creating.value = false
    }
}
</script>
