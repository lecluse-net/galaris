<template>
  <q-page class="flex flex-center auth-page">
    <div class="column items-center">
      <div class="app-brand q-mb-lg">
        <img src="/logo/256.png" alt="Logo" class="app-logo" />
        <div class="text-h1 text-white text-weight-bold">{{ appLabel }}</div>
      </div>

      <q-card class="auth-card">
        <q-card-section class="auth-card__header">
          <div class="auth-card__icon" aria-hidden="true">
            <q-icon name="lock_open" size="28px" />
          </div>
          <div class="auth-card__title">{{ $t('auth.loginTitle') }}</div>
        </q-card-section>
        <q-card-section class="auth-card__body">
          <q-form @submit="onSubmit" class="q-gutter-md">
            <q-input
              v-model="email"
              class="auth-input"
              :label="$t('auth.email')"
              type="email"
              outlined
              :rules="[
                val => !!val || $t('auth.emailRequired'),
                val => isValidEmail(val) || $t('auth.emailInvalid')
              ]"
            >
              <template v-slot:prepend>
                <q-icon name="email" />
              </template>
            </q-input>

            <q-input
              v-if="authStore.mfaRequired"
              v-model="otpCode"
              class="auth-input"
              :label="$t('auth.otpCode')"
              inputmode="numeric"
              autocomplete="one-time-code"
              outlined
              :rules="[val => !!val || $t('auth.otpRequired')]"
            >
              <template #prepend>
                <q-icon name="password" />
              </template>
            </q-input>

            <q-input
              v-model="password"
              class="auth-input"
              :label="$t('auth.password')"
              :type="isPwd ? 'password' : 'text'"
              outlined
              :rules="[val => !!val || $t('auth.passwordRequired')]"
            >
              <template v-slot:prepend>
                <q-icon name="lock" />
              </template>
              <template v-slot:append>
                <q-icon
                  :name="isPwd ? 'visibility_off' : 'visibility'"
                  class="cursor-pointer"
                  @click="isPwd = !isPwd"
                />
              </template>
            </q-input>

            <div v-if="error" class="auth-error q-mt-md" role="alert">
              <q-icon name="error_outline" size="20px" />
              <span>{{ error }}</span>
            </div>

            <div class="q-mt-lg">
              <q-btn
                type="submit"
                class="login-button full-width"
                :loading="loading"
                :disable="loading"
                :label="$t('auth.loginButton')"
                icon-right="arrow_forward"
                no-caps
                unelevated
              />
            </div>
          </q-form>
        </q-card-section>
        <q-card-actions v-if="registrationOpen || registrationStatusError" align="center">
          <q-btn v-if="registrationOpen" flat to="/user/register" :label="$t('auth.registerButton')" />
          <div v-else role="alert">
            {{ $t('auth.registrationStatusError') }}
            <q-btn flat :label="$t('auth.retryRegistrationStatus')" @click="checkRegistration" />
          </div>
        </q-card-actions>

      </q-card>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/authStore'
import { settings } from '../../settings'
import { useRegistrationStatus } from '../useRegistrationStatus'

const router = useRouter()
const $q = useQuasar()
const { t } = useI18n()
const authStore = useAuthStore()
const appLabel = settings.APP_LABEL

const email = ref('')
const password = ref('')
const otpCode = ref('')
const isPwd = ref(true)
const loading = ref(false)
const error = ref('')
const { registrationOpen, registrationStatusError, checkRegistration } = useRegistrationStatus()
onMounted(() => { void checkRegistration() })

function isValidEmail(email: string): boolean {
  const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  return emailPattern.test(email)
}

async function onSubmit(): Promise<void> {
  error.value = ''
  loading.value = true

  try {
    await authStore.login({
      email: email.value,
      password: password.value,
      otp_code: authStore.mfaRequired ? otpCode.value : undefined,
    })
    
    $q.notify({
      type: 'positive',
      message: t('auth.loginSuccess'),
      position: 'top'
    })
    
    router.push('/')
  } catch (err: unknown) {
    error.value = typeof err === 'string' ? err : t('auth.loginError')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.app-brand {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 16px;
}

.app-logo {
  width: 150px;
  height: 150px;
}

.auth-page {
  background-image: url('/background.jpg');
  background-repeat: repeat;
  background-position: center;
}

.auth-card {
  position: relative;
  width: 420px;
  max-width: calc(100vw - 32px);
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow:
    0 28px 70px rgba(4, 20, 48, 0.32),
    0 8px 24px rgba(4, 20, 48, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(18px) saturate(140%);
}

.auth-card::after {
  position: absolute;
  top: -90px;
  right: -82px;
  width: 190px;
  height: 190px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(25, 118, 210, 0.16), transparent 68%);
  content: '';
  pointer-events: none;
}

.auth-card__header {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 32px 32px 12px;
  gap: 14px;
}

.auth-card__icon {
  display: grid;
  width: 58px;
  height: 58px;
  place-items: center;
  color: white;
  border: 1px solid rgba(255, 255, 255, 0.62);
  border-radius: 18px;
  background: linear-gradient(145deg, #268bdc, #6257d9);
  box-shadow: 0 12px 28px rgba(42, 103, 203, 0.32);
  transform: rotate(-3deg);
}

.auth-card__title {
  color: #16304f;
  font-size: 1.65rem;
  font-weight: 750;
  letter-spacing: -0.025em;
  line-height: 1.2;
  text-align: center;
}

.auth-card__body {
  position: relative;
  z-index: 1;
  padding: 18px 32px 34px;
}

.auth-input :deep(.q-field__control) {
  border-radius: 14px;
  background: rgba(244, 248, 253, 0.78);
  transition: background-color 160ms ease, box-shadow 160ms ease;
}

.auth-input :deep(.q-field__control:hover) {
  background: rgba(240, 246, 253, 0.96);
}

.auth-input.q-field--focused :deep(.q-field__control) {
  background: white;
  box-shadow: 0 7px 20px rgba(25, 118, 210, 0.11);
}

.auth-input :deep(.q-field__prepend),
.auth-input :deep(.q-field__append) {
  color: #54708f;
}

.auth-error {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  color: #b42318;
  border: 1px solid rgba(180, 35, 24, 0.18);
  border-radius: 12px;
  gap: 8px;
  background: rgba(254, 243, 242, 0.92);
  font-size: 0.875rem;
}

.login-button {
  min-height: 54px;
  color: white;
  border-radius: 15px;
  background: linear-gradient(115deg, #1976d2 0%, #3e65d5 48%, #6a55d9 100%) !important;
  box-shadow: 0 13px 26px rgba(47, 92, 199, 0.3);
  font-size: 1rem;
  font-weight: 700;
  letter-spacing: 0.01em;
  transition: box-shadow 180ms ease, transform 180ms ease, filter 180ms ease;
}

.login-button:hover,
.login-button:focus-visible {
  box-shadow: 0 17px 32px rgba(47, 92, 199, 0.38);
  filter: brightness(1.07);
  transform: translateY(-2px);
}

.login-button:active {
  box-shadow: 0 8px 18px rgba(47, 92, 199, 0.28);
  transform: translateY(0);
}

body.body--dark .auth-page {
  background-color: #07111f;
  background-image:
    linear-gradient(rgba(3, 9, 19, 0.78), rgba(7, 13, 27, 0.88)),
    url('/background.jpg');
}

body.body--dark .auth-card {
  color: #e7edf7;
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(23, 28, 37, 0.94);
  box-shadow:
    0 28px 70px rgba(0, 0, 0, 0.52),
    0 8px 24px rgba(0, 0, 0, 0.34),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

body.body--dark .auth-card__title {
  color: #e7edf7;
}

body.body--dark .auth-input :deep(.q-field__control) {
  background: rgba(32, 39, 52, 0.82);
}

body.body--dark .auth-input :deep(.q-field__control:hover) {
  background: rgba(38, 46, 61, 0.96);
}

body.body--dark .auth-input.q-field--focused :deep(.q-field__control) {
  background: #202735;
  box-shadow: 0 7px 20px rgba(0, 0, 0, 0.28);
}

body.body--dark .auth-input :deep(.q-field__prepend),
body.body--dark .auth-input :deep(.q-field__append) {
  color: #9eb3cd;
}

body.body--dark .auth-error {
  color: #ffb4ab;
  border-color: rgba(255, 180, 171, 0.22);
  background: rgba(76, 30, 31, 0.72);
}

@media (max-width: 599px) {
  .auth-card {
    border-radius: 24px;
  }

  .auth-card__header {
    padding: 28px 24px 10px;
  }

  .auth-card__body {
    padding: 16px 24px 28px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .auth-input :deep(.q-field__control),
  .login-button {
    transition: none;
  }
}

</style>
