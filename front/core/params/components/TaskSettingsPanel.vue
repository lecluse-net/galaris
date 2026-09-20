<template>
    <div class="task-settings-panel">
        <div class="text-h6 text-primary q-mb-sm">{{ t('taskSettings.title') }}</div>
        <div class="text-body2 text-grey-7 q-mb-lg">{{ t('taskSettings.subtitle') }}</div>

        <q-banner rounded class="task-settings-warning q-mb-lg">
            <template #avatar>
                <q-icon name="warning_amber" color="warning" size="md" />
            </template>
            <div class="text-subtitle2">{{ t('taskSettings.warningTitle') }}</div>
            <div class="text-body2">{{ t('taskSettings.warning') }}</div>
        </q-banner>

        <SettingsBlock v-for="group in groups" :key="group.key"
            :title="t(`taskSettings.groups.${group.key}.title`)"
            :description="t(`taskSettings.groups.${group.key}.subtitle`)"
            :icon="group.icon" :advanced="group.advanced">
            <SettingsFields :fields="group.fields" :columns="2" :expand-advanced="!group.advanced" />
        </SettingsBlock>
        <component v-for="contribution in taskExecutionSettings" :key="contribution.kind"
            :is="contribution.taskExecutionComponent" />
    </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { taskGroups as groups } from '../settingsLayout'
import { taskExecutionSettings } from '../bridgeSettings'
import SettingsBlock from './SettingsBlock.vue'
import SettingsFields from './SettingsFields.vue'

const { t } = useI18n()
</script>

<style scoped>
.task-settings-warning {
    background: var(--solaire-orange-light);
    color: inherit;
}

body.body--dark .task-settings-warning {
    background: var(--solaire-orange-dark);
}

@media (max-width: 1023px) {
    .task-settings-warning {
        margin-bottom: 20px;
    }
}

@media (max-width: 599px) {
    .task-settings-warning :deep(.q-banner__avatar) {
        padding-right: 8px;
    }

    .task-settings-group :deep(.q-field__label) {
        max-width: calc(100% - 12px);
    }
}
</style>
