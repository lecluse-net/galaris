<template>
    <div>
        <div class="text-h6 text-primary q-mb-sm">{{ t('memorySettings.title') }}</div>
        <div class="text-body2 text-grey-7 q-mb-lg">{{ t('memorySettings.subtitle') }}</div>

        <q-banner rounded class="memory-guide q-mb-lg">
            <template #avatar>
                <q-icon name="verified_user" color="primary" size="md" />
            </template>
            {{ t('memorySettings.governanceHint') }}
        </q-banner>

        <SettingsBlock v-for="group in groups" :key="group.key"
            :title="t(`memorySettings.groups.${group.key}.title`)"
            :description="t(`memorySettings.groups.${group.key}.subtitle`)" :icon="group.icon">
            <q-banner v-if="group.key === 'automation'" rounded class="dream-execution-guide q-mb-lg">
                <template #avatar>
                    <q-icon name="bedtime" color="primary" size="md" />
                </template>
                <div class="text-subtitle2 text-weight-medium">{{ t('memorySettings.dreamExecution.title') }}</div>
                <div class="text-body2 q-mt-xs">{{ t('memorySettings.dreamExecution.description') }}</div>
                <q-btn
                    to="/params/dream"
                    outline
                    color="primary"
                    icon="tune"
                    :label="t('memorySettings.dreamExecution.openSettings')"
                    no-caps
                    class="q-mt-md"
                />
            </q-banner>
            <template v-if="group.key === 'automation'">
                <div v-for="maintenance in memoryMaintenanceGroups" :key="maintenance.key" class="memory-maintenance">
                    <h3 class="text-subtitle2 q-mt-md q-mb-sm">{{ t(`configuration.layout.${maintenance.key}`) }}</h3>
                    <SettingsFields :fields="maintenance.fields" :columns="2" />
                </div>
                <SettingsFields :fields="memoryRuntimeFields.map(field => ({ ...field, advanced: true }))"
                    :columns="2" :advanced-label="t('configuration.layout.backgroundExecution')" />
            </template>
            <SettingsFields v-else :fields="group.fields" :columns="2" />
        </SettingsBlock>
        <SettingsBlock :title="t('storageSettings.title')" icon="storage">
            <SettingsFields :fields="memoryStorageFields" />
        </SettingsBlock>
    </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import {
    memoryContextFields,
    memorySessionFields,
    memoryStorageFields,
} from '../settingsCatalog'
import SettingsFields from './SettingsFields.vue'
import SettingsBlock from './SettingsBlock.vue'
import { memoryMaintenanceGroups, memoryRuntimeFields } from '../settingsLayout'

const { t } = useI18n()
const groups = [
    { key: 'context', icon: 'psychology', fields: memoryContextFields },
    { key: 'session', icon: 'forum', fields: memorySessionFields },
    { key: 'automation', icon: 'auto_fix_high', fields: [] },
] as const
</script>

<style scoped>
.memory-guide {
    color: inherit;
    background: var(--solaire-blue-light);
}

.dream-execution-guide {
    color: inherit;
    background: var(--solaire-violet-light);
}

.memory-maintenance + .memory-maintenance {
    border-top: 1px solid color-mix(in srgb, currentColor 16%, transparent);
}
body.body--dark .memory-guide { background: var(--solaire-blue-dark); }
body.body--dark .dream-execution-guide { background: var(--solaire-violet-dark); }
</style>
