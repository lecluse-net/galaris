<template>
  <q-btn :to="destination" :loading="loading" @click="navigate">
    <slot />
  </q-btn>
</template>

<script setup lang="ts">
import { onMounted, onScopeDispose, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { authService } from '../services/authService'

const router = useRouter()
const $q = useQuasar()
const { t } = useI18n()
const destination = ref<string>()
const loading = ref(true)
let active = true
onScopeDispose(() => { active = false })

async function resolveDestination(): Promise<string | undefined> {
  loading.value = true
  try {
    const { initial_admin_required } = await authService.getRegistrationStatus()
    if (!active) return
    destination.value = initial_admin_required ? '/user/register' : '/user/login'
    return destination.value
  } catch {
    if (active) {
      destination.value = undefined
      $q.notify({ type: 'negative', message: t('auth.registrationStatusError') })
    }
  } finally {
    if (active) loading.value = false
  }
}

async function navigate(event: Event): Promise<void> {
  // Keep ordinary link behavior for opening a new tab. Recheck on activation
  // because another visitor may have created the first account in the meantime.
  if (event instanceof MouseEvent && (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)) return
  event.preventDefault()
  const path = await resolveDestination()
  if (path) await router.push(path)
}

onMounted(() => { void resolveDestination() })
</script>
