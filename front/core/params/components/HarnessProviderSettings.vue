<template>
  <section v-if="contribution" class="q-pa-lg">
    <div v-if="loading" class="row justify-center q-pa-lg">
      <q-spinner color="primary" size="36px" />
    </div>
    <q-banner v-else-if="loadFailed" rounded class="bg-red-1 text-negative">
      {{ t('common.anError') }}
      <template #action>
        <q-btn flat :label="t('common.retry')" @click="load" />
      </template>
    </q-banner>
    <BridgeSettingsPanel v-else :contribution="contribution" :show-guide="false" />
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { harnessBridgeSettings } from '../bridgeSettings'
import { useParamsStore } from '../stores/paramsStore'
import BridgeSettingsPanel from './BridgeSettingsPanel.vue'

const props = defineProps<{ provider: string }>()
const { t } = useI18n()
const paramsStore = useParamsStore()
const contribution = computed(() => harnessBridgeSettings.find(item => item.kind === props.provider))
const loading = ref(false)
const loadFailed = ref(false)

async function load(): Promise<void> {
  if (!contribution.value) return
  loading.value = true
  loadFailed.value = false
  try {
    await paramsStore.fetchParams()
    loadFailed.value = Boolean(paramsStore.error)
  } catch {
    loadFailed.value = true
  } finally {
    loading.value = false
  }
}

watch(() => props.provider, load, { immediate: true })
</script>
