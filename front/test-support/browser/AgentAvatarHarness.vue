<template>
  <div v-if="showManagement" class="management-avatars">
    <AgentAvatar v-for="index in 2" :key="index" :agent-id="agentId" name="Test Agent" :has-avatar="hasAvatar" />
  </div>
  <InternalAgentAvatar v-if="showChat" class="chat-avatar" :agent-id="agentId" name="Test Agent" />
</template>

<script setup lang="ts">
import { AgentAvatar } from '@/app/agent'
import InternalAgentAvatar from '@/app/chat/components/InternalAgentAvatar.vue'
withDefaults(defineProps<{ agentId?: number; hasAvatar?: boolean; showManagement?: boolean; showChat?: boolean }>(), {
  agentId: 7, hasAvatar: true, showManagement: true, showChat: false,
})
</script>
