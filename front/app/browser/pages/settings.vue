<template>
    <q-page class="q-pa-md">
        <PageHeader help-key="browser" :help-text="$t('contextHelpPages.browser')" :icon="navigationIcon('web')" :title="t('browserSettings.title')" :description="t('browserSettings.subtitle')" />
        <div v-if="availability.failed || (params.error && !params.params.length)" class="q-mt-md">
            <q-banner class="bg-negative text-white" rounded>{{ t('browserSettings.loadError') }}</q-banner>
            <q-btn class="q-mt-md" :label="t('browserSettings.retry')" @click="retry" />
        </div>
        <div v-else-if="availability.available !== true || (params.loading && !params.params.length)" class="row justify-center q-pa-lg">
            <q-spinner color="primary" size="3em" />
        </div>
        <q-card v-else flat bordered class="q-pa-md browser-settings">
            <SettingsFields :fields="browserFields" :columns="2" />
        </q-card>
        <q-btn flat color="primary" class="q-mt-md" icon="arrow_back" :label="t('common.back')" to="/params" />
    </q-page>
</template>

<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { navigationIcon } from '@/core/navigation'
import { PageHeader } from '@/core/util'
import { SettingsFields, useParamsStore } from '@/core/params'
import { browserFields } from '../settingsFields'
import { useBrowserSettingsStore } from '../stores/browserSettingsStore'

const { t } = useI18n()
const router = useRouter()
const params = useParamsStore()
const availability = useBrowserSettingsStore()
watch(() => availability.available, enabled => {
    if (enabled === false) void router.replace('/params')
    if (enabled === true) void params.fetchParams()
}, { immediate: true })
async function retry(): Promise<void> {
    await availability.refresh()
    if (availability.available) await params.fetchParams()
}
onMounted(() => { if (!availability.loading) void availability.refresh() })
</script>

<style scoped>
.browser-settings { max-width: 1280px; }
</style>
