<template>
  <q-page class="flex flex-center auth-page">
    <q-card class="invitation-card q-pa-md">
      <q-card-section>
        <div class="text-h5 text-center text-primary">{{ t('userInvitation.title') }}</div>
      </q-card-section>
      <q-card-section>
        <q-form v-if="validLink" class="column q-gutter-md" @submit="accept">
          <PasswordFields v-model="password" v-model:confirmation="confirmation" label-key="userEdit.newPassword" stacked />
          <div v-if="error" role="alert" class="text-negative">{{ error }}</div>
          <q-btn type="submit" color="primary" :label="t('userInvitation.activate')" :loading="loading" />
        </q-form>
        <div v-else role="alert">{{ t('userInvitation.invalidLink') }}</div>
      </q-card-section>
      <q-card-actions align="center">
        <q-btn outline color="primary" to="/user/login" :label="t('auth.loginButton')" />
      </q-card-actions>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import PasswordFields from '../components/PasswordFields.vue'
import { authService } from '../services/authService'

const route = useRoute()
const router = useRouter()
const $q = useQuasar()
const { t } = useI18n()
const token = computed(() => route.hash.slice(1))
const validLink = computed(() => /^[A-Za-z0-9_-]{43}$/.test(token.value))
const password = ref('')
const confirmation = ref('')
const error = ref('')
const loading = ref(false)

watch(token, () => {
  password.value = ''
  confirmation.value = ''
  error.value = ''
  loading.value = false
})

async function accept() {
  if (!validLink.value || loading.value) return
  const submittedToken = token.value
  loading.value = true
  error.value = ''
  try {
    await authService.acceptInvitation(submittedToken, password.value, confirmation.value)
    if (submittedToken !== token.value) return
    $q.notify({ type: 'positive', message: t('userInvitation.activated') })
    await router.replace('/user/login')
  } catch (failure) {
    if (submittedToken === token.value) error.value = apiErrorDetail(failure) ?? t('common.anError')
  } finally {
    if (submittedToken === token.value) loading.value = false
  }
}
</script>

<style scoped>
.auth-page { background-image: url('/background.jpg'); }
.invitation-card { width: 400px; max-width: 90vw; }
</style>
