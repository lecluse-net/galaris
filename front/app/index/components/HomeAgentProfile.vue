<template>
  <q-dialog :model-value="true" :aria-labelledby="titleId" @hide="emit('close')">
    <q-card class="galaris-dialog-card agent-profile">
      <q-card-section class="galaris-dialog-title">
        <h2 :id="titleId" class="text-h6 q-ma-none">{{ agent.display_name }}</h2>
        <q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>

      <q-card-section v-if="loading" role="status">
        <q-spinner color="primary" class="q-mr-sm" />{{ t('common.loading') }}
      </q-card-section>
      <q-card-section v-else-if="failed">
        <q-banner rounded role="alert">
          {{ t('index.userHome.profileError') }}
          <template #action>
            <q-btn outline color="primary" :label="t('common.retry')" @click="retry++" />
          </template>
        </q-banner>
      </q-card-section>
      <q-card-section v-else-if="profile" class="agent-profile__content">
        <div class="row items-center q-gutter-md">
          <AgentAvatar :agent-id="agent.agent_id" :name="agent.display_name" size="88px" dialogue />
          <div v-if="profile.job_title" class="text-subtitle1 text-weight-medium">{{ profile.job_title }}</div>
        </div>
        <section class="q-mt-md">
          <h3 class="text-subtitle1 text-weight-bold q-my-sm">{{ t('agent.jobDescription') }}</h3>
          <RichText v-if="profile.job_description" :content="profile.job_description" />
          <div v-else>{{ t('index.userHome.profileEmpty') }}</div>
        </section>
        <section class="q-mt-md">
          <h3 class="text-subtitle1 text-weight-bold q-my-sm">{{ t('agent.personality') }}</h3>
          <RichText v-if="profile.personality" :content="profile.personality" />
          <div v-else>{{ t('index.userHome.profileEmpty') }}</div>
        </section>
        <section class="q-mt-md">
          <h3 class="text-subtitle1 text-weight-bold q-my-sm">{{ t('index.userHome.externalServices') }}</h3>
          <div v-if="profile.external_services.length" class="row q-gutter-xs">
            <q-chip v-for="service in profile.external_services" :key="service.code" class="bg-solaire-cyan-light">
              {{ service.label }}
            </q-chip>
          </div>
          <div v-else>{{ t('index.userHome.noExternalServices') }}</div>
        </section>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RichText } from '@/core/util'
import { AgentAvatar } from '@/app/agent'
import { agentDialogueService, type DialogueAgent, type DialogueAgentProfile } from '@/app/agent/facade'

const { agent } = defineProps<{ agent: DialogueAgent }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const titleId = useId()
const profile = ref<DialogueAgentProfile | null>(null)
const retry = ref(0)
const loading = ref(true)
const failed = ref(false)

watch([() => agent.agent_id, retry], async ([agentId], _, onCleanup) => {
  const request = new AbortController()
  onCleanup(() => request.abort())
  profile.value = null
  failed.value = false
  loading.value = true
  try {
    const data = await agentDialogueService.profile(agentId, request.signal)
    if (!request.signal.aborted) profile.value = data
  } catch {
    if (!request.signal.aborted) failed.value = true
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}, { immediate: true })
</script>

<style scoped>
.agent-profile { width: 620px; max-width: calc(100vw - 32px); }
.agent-profile__content { overflow-wrap: anywhere; }
</style>
