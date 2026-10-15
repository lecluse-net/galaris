<template>
  <q-page class="q-pa-md">
    <q-card flat bordered>
      <q-card-section>
        <h1 class="text-h6">{{ t('connection.oauth.title') }}</h1>
        <q-spinner v-if="loading" class="q-mr-sm" />
        <div role="status">{{ message }}</div>
      </q-card-section>
      <q-card-actions>
        <q-btn v-if="!loading" color="primary" :label="t('connection.oauth.back')" to="/tools?tab=connections" />
      </q-card-actions>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { mcpOAuthService } from '../services/mcpOAuthService'

const { t } = useI18n()
const loading = ref(true)
const message = ref(t('connection.oauth.loading'))
const query = new URLSearchParams(window.location.search)
// Remove the authorization code before rendering links or loading more assets.
window.history.replaceState(window.history.state, '', window.location.pathname)
onMounted(async () => {
  try {
    await mcpOAuthService.complete(query)
    message.value = t('connection.oauth.success')
  } catch (cause) {
    message.value = apiErrorDetail(cause) || t('connection.oauth.failed')
  } finally { loading.value = false }
})
</script>
