<template>
  <q-card flat :bordered="!embedded">
    <q-card-section>
      <div class="row items-center q-gutter-sm">
        <q-icon name="security" color="primary" size="sm" />
        <div class="text-h6">{{ t('mfa.title') }}</div>
        <q-space />
        <q-chip
          :color="mfaStatus.enabled ? 'positive' : 'grey-6'"
          text-color="white"
          dense
        >
          {{ mfaStatus.enabled ? t('mfa.enabled') : t('mfa.disabled') }}
        </q-chip>
      </div>
      <div class="text-caption text-grey-7 q-mt-xs">{{ t('mfa.description') }}</div>
    </q-card-section>

    <q-separator />

    <q-card-section v-if="loading" class="text-center">
      <q-spinner color="primary" />
    </q-card-section>

    <q-card-section v-else-if="!mfaStatus.enabled" class="mfa-setup">
      <q-btn
        v-if="!setup"
        color="primary"
        icon="add_moderator"
        :label="t('mfa.startSetup')"
        @click="startSetup"
      />

      <template v-else>
        <q-banner rounded class="bg-blue-1 text-blue-10">
          {{ t('mfa.setupHint') }}
        </q-banner>

        <div class="mfa-setup-grid">
          <div class="mfa-qr-column">
            <div class="mfa-qr-frame">
              <q-spinner v-if="qrCodeLoading" color="primary" size="40px" />
              <img
                v-else-if="qrCodeDataUrl"
                :src="qrCodeDataUrl"
                :alt="t('mfa.qrCodeAlt')"
                class="mfa-qr-code"
              />
              <q-icon v-else name="qr_code_2" color="grey-6" size="64px" />
            </div>
          </div>

          <div class="mfa-setup-fields">
            <q-input :model-value="setup.secret" :label="t('mfa.secret')" readonly outlined>
              <template #append>
                <q-btn
                  flat
                  round
                  icon="content_copy"
                  :aria-label="t('common.copyShort')"
                  @click="copy(setup.secret)"
                />
              </template>
            </q-input>
            <q-input
              v-model="confirmationCode"
              :label="t('mfa.code')"
              autocomplete="one-time-code"
              inputmode="numeric"
              outlined
            />
            <q-btn
              color="positive"
              icon="verified_user"
              :label="t('mfa.confirm')"
              :disable="!confirmationCode"
              @click="confirmSetup"
            />
          </div>
        </div>
        <div class="text-caption text-grey-7">
          {{ t('mfa.qrCodeHint') }}
        </div>
      </template>
    </q-card-section>

    <q-card-section v-else class="q-gutter-md">
      <div>
        {{ t('mfa.recoveryRemaining', { count: mfaStatus.recovery_codes_remaining }) }}
      </div>
      <q-input
        v-model="managementCode"
        :label="t('mfa.currentCode')"
        autocomplete="one-time-code"
        outlined
      />
      <q-btn
        outline
        color="primary"
        icon="refresh"
        :label="t('mfa.regenerate')"
        :disable="!managementCode"
        @click="regenerate"
      />
      <q-expansion-item icon="remove_moderator" :label="t('mfa.disableAction')">
        <div class="q-pa-sm q-gutter-md">
          <q-input
            v-model="password"
            type="password"
            :label="t('auth.password')"
            autocomplete="current-password"
            outlined
          />
          <q-btn
            color="negative"
            :label="t('mfa.disableConfirm')"
            :disable="!password || !managementCode"
            @click="disable"
          />
        </div>
      </q-expansion-item>
    </q-card-section>

    <q-card-section v-if="recoveryCodes.length" class="q-pt-none">
      <q-banner rounded class="bg-orange-1 text-orange-10 q-mb-sm">
        {{ t('mfa.recoveryWarning') }}
      </q-banner>
      <q-list bordered separator>
        <q-item v-for="code in recoveryCodes" :key="code">
          <q-item-section class="text-monospace">{{ code }}</q-item-section>
        </q-item>
      </q-list>
      <q-btn
        flat
        icon="content_copy"
        :label="t('mfa.copyRecovery')"
        class="q-mt-sm"
        @click="copy(recoveryCodes.join('\n'))"
      />
    </q-card-section>
  </q-card>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import QRCode from 'qrcode'
import {
  authService,
  type MfaSetup,
  type MfaStatus,
} from '@/core/user/services/authService'

const { embedded = false } = defineProps<{
  embedded?: boolean
}>()

const { t } = useI18n()
const $q = useQuasar()
const loading = ref(true)
const setup = ref<MfaSetup | null>(null)
const confirmationCode = ref('')
const managementCode = ref('')
const password = ref('')
const recoveryCodes = ref<string[]>([])
const qrCodeDataUrl = ref('')
const qrCodeLoading = ref(false)
const mfaStatus = reactive<MfaStatus>({
  enabled: false,
  setup_pending: false,
  recovery_codes_remaining: 0,
})

watch(() => setup.value?.provisioning_uri ?? '', async provisioningUri => {
  qrCodeDataUrl.value = ''
  if (!provisioningUri) return

  qrCodeLoading.value = true
  try {
    const generatedUrl = await QRCode.toDataURL(provisioningUri, {
      errorCorrectionLevel: 'M',
      margin: 2,
      width: 220,
      color: {
        dark: '#000000',
        light: '#ffffff',
      },
    })
    if (setup.value?.provisioning_uri === provisioningUri) {
      qrCodeDataUrl.value = generatedUrl
    }
  } catch {
    qrCodeDataUrl.value = ''
  } finally {
    qrCodeLoading.value = false
  }
})

async function refreshStatus(): Promise<void> {
  Object.assign(mfaStatus, await authService.getMfaStatus())
}

async function startSetup(): Promise<void> {
  try {
    setup.value = await authService.setupMfa()
    recoveryCodes.value = []
  } catch {
    $q.notify({ type: 'negative', message: t('mfa.operationError') })
  }
}

async function confirmSetup(): Promise<void> {
  try {
    const response = await authService.confirmMfa(confirmationCode.value)
    recoveryCodes.value = response.recovery_codes
    setup.value = null
    confirmationCode.value = ''
    await refreshStatus()
    $q.notify({ type: 'positive', message: t('mfa.enabledSuccess') })
  } catch {
    $q.notify({ type: 'negative', message: t('mfa.invalidCode') })
  }
}

async function regenerate(): Promise<void> {
  try {
    const response = await authService.regenerateMfaRecoveryCodes(managementCode.value)
    recoveryCodes.value = response.recovery_codes
    managementCode.value = ''
    await refreshStatus()
  } catch {
    $q.notify({ type: 'negative', message: t('mfa.invalidCode') })
  }
}

async function disable(): Promise<void> {
  try {
    await authService.disableMfa(password.value, managementCode.value)
    password.value = ''
    managementCode.value = ''
    recoveryCodes.value = []
    await refreshStatus()
    $q.notify({ type: 'positive', message: t('mfa.disabledSuccess') })
  } catch {
    $q.notify({ type: 'negative', message: t('mfa.invalidCredentials') })
  }
}

async function copy(value: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value)
    $q.notify({ type: 'positive', message: t('mfa.copied') })
  } catch {
    $q.notify({ type: 'negative', message: t('mfa.copyFailed') })
  }
}

onMounted(async () => {
  try {
    await refreshStatus()
    if (mfaStatus.setup_pending) {
      setup.value = await authService.setupMfa()
    }
  } catch {
    $q.notify({ type: 'negative', message: t('mfa.loadError') })
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.mfa-setup,
.mfa-setup-grid,
.mfa-setup-fields {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.mfa-setup-grid {
  align-items: center;
}

.mfa-qr-column {
  display: grid;
  place-items: center;
  min-width: 0;
}

.mfa-setup-fields > .q-btn,
.mfa-setup > .q-btn {
  justify-self: start;
}

.mfa-qr-frame {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  width: 100%;
  max-width: 236px;
  min-width: 0;
  aspect-ratio: 1;
  place-items: center;
  margin: 0 auto;
  padding: 8px;
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 8px;
  background: white;
}

.mfa-qr-code {
  display: block;
  width: 100%;
  max-width: 220px;
  height: auto;
}

@media (min-width: 1024px) {
  .mfa-setup-grid {
    grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
  }
}
</style>
