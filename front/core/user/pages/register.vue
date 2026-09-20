<template>
  <q-page class="flex flex-center auth-page">
    <div class="column items-center">
      <div class="app-brand q-mb-lg">
        <img src="/logo/256.png" alt="Logo" class="app-logo" />
        <div class="text-h1 text-white text-weight-bold">{{ appLabel }}</div>
      </div>

      <q-card class="q-pa-md" style="width: 400px; max-width: 90vw">
      <q-card-section>
        <div class="text-h5 text-center text-primary">{{ $t('auth.registerTitle') }}</div>
      </q-card-section>

      <q-card-section>
        <q-spinner v-if="checkingRegistration" color="primary" />
        <div v-else-if="registrationStatusError" role="alert">
          {{ $t('auth.registrationStatusError') }}
          <q-btn flat :label="$t('auth.retryRegistrationStatus')" @click="refreshRegistration" />
        </div>
        <q-form v-else-if="registrationOpen" @submit="onSubmit" class="q-gutter-md">
          <q-input
            v-model="email"
            :label="$t('auth.email')"
            type="email"
            outlined
            dense
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
            v-model="password"
            :label="$t('auth.password')"
            :type="isPwd ? 'password' : 'text'"
            outlined
            dense
            maxlength="72"
            :rules="[
              val => !!val || $t('auth.passwordRequired'),
              val => val.length >= 12 || $t('auth.passwordMinChars')
            ]"
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

          <q-input
            v-model="confirmPassword"
            :label="$t('auth.confirmPassword')"
            :type="isConfirmPwd ? 'password' : 'text'"
            outlined
            dense
            maxlength="72"
            :rules="[
              val => !!val || $t('auth.confirmRequired'),
              val => val === password || $t('auth.passwordMismatch')
            ]"
          >
            <template v-slot:prepend>
              <q-icon name="lock" />
            </template>
            <template v-slot:append>
              <q-icon
                :name="isConfirmPwd ? 'visibility_off' : 'visibility'"
                class="cursor-pointer"
                @click="isConfirmPwd = !isConfirmPwd"
              />
            </template>
          </q-input>

          <div v-if="error" class="text-negative q-mt-md">
            {{ error }}
          </div>

          <div class="q-mt-md">
            <q-btn
              type="submit"
              color="primary"
              class="full-width"
              :loading="loading"
              :disable="loading"
              :label="$t('auth.registerButton')"
              unelevated
            />
          </div>
        </q-form>
      </q-card-section>
      <q-card-actions align="center">
        <q-btn flat to="/user/login" :label="$t('auth.loginButton')" />
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
const confirmPassword = ref('')
const isPwd = ref(true)
const isConfirmPwd = ref(true)
const loading = ref(false)
const error = ref('')
const { registrationOpen, checkingRegistration, registrationStatusError, checkRegistration } = useRegistrationStatus()

async function refreshRegistration(): Promise<void> {
  if (await checkRegistration() === false) await router.replace('/user/login')
}

onMounted(() => { void refreshRegistration() })

function isValidEmail(email: string): boolean {
  const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  return emailPattern.test(email)
}

async function onSubmit() {
  if (!registrationOpen.value || loading.value) return
  error.value = ''
  loading.value = true

  try {
    await authStore.register({
      email: email.value,
      password: password.value
    })
    
    $q.notify({
      type: 'positive',
      message: t('auth.registerSuccess'),
      position: 'top'
    })
    
    router.push('/')
  } catch (err) {
    error.value = typeof err === 'string' ? err : t('auth.registerError')
    await refreshRegistration()
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

</style>
