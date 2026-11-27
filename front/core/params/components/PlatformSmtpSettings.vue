<template>
    <SettingsBlock :title="t('platformSmtp.title')" :description="t('platformSmtp.description')" icon="mail">
        <h3 class="text-subtitle2 q-mt-sm q-mb-none">{{ t('platformSmtp.serverSettings') }}</h3>
        <SettingsFields :fields="platformSmtpServerFields" :columns="2" />

        <q-separator class="q-my-sm" />
        <h3 class="text-subtitle2 q-mb-none">{{ t('platformSmtp.securitySettings') }}</h3>
        <SettingsFields :fields="securityFields" :columns="2" />

        <template v-if="canTest">
            <q-separator class="q-my-sm" />
            <PlatformSmtpTestForm />
        </template>
    </SettingsBlock>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { platformSmtpCredentialFields, platformSmtpSecurityFields, platformSmtpServerFields } from '../settingsCatalog'
import { useParamsStore } from '../stores/paramsStore'
import PlatformSmtpTestForm from './PlatformSmtpTestForm.vue'
import SettingsBlock from './SettingsBlock.vue'
import SettingsFields from './SettingsFields.vue'

defineProps<{ canTest: boolean }>()

const { t } = useI18n()
const paramsStore = useParamsStore()
const securityFields = computed(() => {
    const authentication = paramsStore.getParamValue('PLATFORM_SMTP_AUTHENTICATION')
    return authentication === 'none' || authentication === 'gssapi'
        ? platformSmtpSecurityFields
        : [...platformSmtpSecurityFields, ...platformSmtpCredentialFields]
})
</script>
