<template>
  <ChatNotificationBootstrap />
  <ChatPage v-if="route.path === '/chat'" />
  <DocumentLibraryPage v-else />
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import ChatNotificationBootstrap from '@/app/chat/components/ChatNotificationBootstrap.vue'
import ChatPage from '@/app/chat/pages/index.vue'
import DocumentLibraryPage from '@/app/document/components/DocumentLibraryPage.vue'
const route = useRoute()
</script>
