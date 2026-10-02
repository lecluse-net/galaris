<template>
  <header class="chat-welcome">
    <h2>{{ t(canCreate ? 'chat.home.title' : 'chat.conversations') }}</h2>
    <p>{{ t(canCreate ? 'chat.home.subtitle' : 'chat.home.resume') }}</p>
    <template v-if="canCreate">
      <div v-if="loading" class="welcome-status" role="status">
        <q-spinner size="24px" /> {{ t('chat.home.loadingAgents') }}
      </div>
      <div v-else-if="error" class="welcome-status" role="alert">
        <span>{{ t('chat.home.agentsError') }}</span>
        <q-btn flat no-caps :label="t('chat.home.retry')" @click="emit('retry')" />
      </div>
      <div v-else>
        <div class="welcome-agents">
          <q-btn
            v-for="agent in agents"
            :key="agent.agent_id"
            no-caps flat class="welcome-agent"
            :aria-label="t('chat.home.startWith', { name: agent.display_name })"
            @click="emit('create', agent.agent_id)"
          >
            <InternalAgentAvatar :agent-id="agent.agent_id" :name="agent.display_name" size="44px" class="welcome-agent-avatar" />
            <span class="welcome-agent-name" :title="agent.display_name">{{ agent.display_name }}</span>
            <q-icon name="add" size="18px" class="welcome-agent-add" />
          </q-btn>
        </div>
      </div>
      <slot name="pagination" />
    </template>
  </header>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { MessengerAgent } from '../types'
import InternalAgentAvatar from './InternalAgentAvatar.vue'

defineProps<{ agents: MessengerAgent[]; canCreate: boolean; loading: boolean; error: boolean }>()
const emit = defineEmits<{ create: [agentId?: number]; retry: [] }>()
const { t } = useI18n()
</script>

<style scoped>
.chat-welcome { padding: 16px 0 32px; }
.chat-welcome h2 { margin: 20px 0 10px; font-size: 1.15rem; font-weight: 600; line-height: 1.4; overflow-wrap: anywhere; }
.chat-welcome p { margin: 0; color: var(--chat-text-secondary); font-size: 1rem; line-height: 1.6; }
.welcome-agents { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 24px; }
.welcome-agent { padding: 10px 16px 10px 10px; border: 1px solid var(--chat-border-strong); border-radius: 14px; background: var(--chat-surface); max-width: 100%; }
.welcome-agent :deep(.q-btn__content) { flex-wrap: nowrap; align-items: center; justify-content: flex-start; gap: 12px; width: 100%; max-width: 100%; }
.welcome-agent-avatar { flex-shrink: 0; }
.welcome-agent-name { text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.welcome-agent-add { margin-left: auto; flex-shrink: 0; color: var(--solaire-blue-accent); }
.welcome-status { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-top: 24px; color: var(--chat-text-secondary); }
@media (max-width: 599px) {
  .chat-welcome { padding-top: 4px; }
  .welcome-agents { gap: 8px; }
  .welcome-agent { flex: 1 1 160px; }
}
</style>
