<template>
    <div :class="{ 'bridge-settings--organized': organized }">
        <template v-if="organized">
            <component v-if="contribution.headerComponent" :is="contribution.headerComponent" />
            <component v-if="contribution.component" :is="contribution.component" class="q-mb-lg" />
            <SettingsBlock v-if="contribution.fields.length" :title="contribution.label" :icon="contribution.icon">
                <SettingsFields :key="contribution.kind" :fields="contribution.fields" :columns="2" />
            </SettingsBlock>
            <SettingsBlock v-for="group in contribution.groups ?? []" :key="group.titleKey"
                :title="t(group.titleKey)" :description="group.descriptionKey ? t(group.descriptionKey) : undefined"
                icon="tune" advanced>
                <SettingsFields :fields="group.fields" :columns="2" :expand-advanced="false" />
            </SettingsBlock>
        </template>

        <component :is="organized ? SettingsBlock : 'div'" v-if="showGuide"
            :title="t('configuration.layout.setupGuide')" icon="help_outline" :advanced="organized">
        <q-banner rounded class="configuration-guide q-mb-lg">
            <template #avatar>
                <q-avatar color="primary" text-color="white" :icon="contribution.icon" />
            </template>
            <div class="text-subtitle1 text-weight-medium">{{ contribution.label }}</div>
            <div class="text-body2 q-mt-xs">{{ t(contribution.guideKey) }}</div>
            <ol class="q-pl-lg q-mb-sm">
                <li v-for="step in setupSteps" :key="step" class="q-mb-xs">{{ step }}</li>
            </ol>
            <q-btn
                :href="contribution.docsUrl"
                target="_blank"
                rel="noopener noreferrer"
                outline
                color="primary"
                icon="open_in_new"
                :label="t('configuration.openDocumentation')"
                no-caps
            />
        </q-banner>
        </component>

        <template v-if="!organized">
        <component v-if="contribution.headerComponent" :is="contribution.headerComponent" />
        <SettingsFields :fields="contribution.fields" />

        <template v-for="(group, index) in contribution.groups ?? []" :key="group.titleKey">
            <q-separator v-if="showGuide || index > 0" class="q-my-xl" />
            <div class="text-subtitle1 text-weight-medium q-mb-xs">{{ t(group.titleKey) }}</div>
            <div v-if="group.descriptionKey" class="text-caption text-grey-7 q-mb-lg">
                {{ t(group.descriptionKey) }}
            </div>
            <SettingsFields :fields="group.fields" />
        </template>

        <template v-if="contribution.component">
            <q-separator class="q-my-xl" />
            <component :is="contribution.component" />
        </template>
        </template>

        <div v-if="contribution.test" class="row items-center q-gutter-sm q-mt-lg">
            <q-btn
                v-if="canEdit"
                color="primary"
                icon="health_and_safety"
                :label="t('configuration.testConfiguration')"
                :loading="testing"
                no-caps
                @click="runTest"
            />
            <q-chip v-if="testStatus" :color="testStatus.ok ? 'positive' : 'negative'" text-color="white">
                {{ testStatus.message }}
            </q-chip>
        </div>
    </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import type { BridgeSettingsContribution } from '../settingsTypes'
import SettingsFields from './SettingsFields.vue'
import SettingsBlock from './SettingsBlock.vue'
import { privileges, usePrivilegeStore } from '@/core/authorize'

const props = withDefaults(defineProps<{
    contribution: BridgeSettingsContribution
    showGuide?: boolean
    organized?: boolean
}>(), { showGuide: true, organized: false })
const { t, tm } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.PARAMS_EDIT))
const testing = ref(false)
const testStatus = ref<{ ok: boolean; message: string } | null>(null)
const setupSteps = computed(() => {
    const translated = tm(props.contribution.stepsKey)
    return Array.isArray(translated) ? translated.map(step => String(step)) : []
})

async function runTest(): Promise<void> {
    if (!canEdit.value) return
    testing.value = true
    testStatus.value = null
    try {
        const result = await props.contribution.test?.()
        if (!result) return
        testStatus.value = {
            ok: result.ok,
            message: result.message
                || t(result.ok ? 'configuration.testSuccess' : 'configuration.testNeedsAttention'),
        }
    } catch {
        $q.notify({ type: 'negative', message: t('configuration.testError') })
    } finally {
        testing.value = false
    }
}
</script>

<style scoped>
.configuration-guide {
    color: inherit;
    background: color-mix(in srgb, var(--q-primary) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--q-primary) 24%, transparent);
}
.bridge-settings--organized .configuration-guide {
    background: var(--solaire-blue-light);
    border: 0;
}
body.body--dark .bridge-settings--organized .configuration-guide { background: var(--solaire-blue-dark); }
</style>
