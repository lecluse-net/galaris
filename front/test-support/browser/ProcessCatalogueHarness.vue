<template>
  <ProcessPage v-if="route.path === '/process'" />
  <q-page v-else class="q-pa-md"><ExternalProcessEditor :id="Number(route.params.id || route.path.split('/').at(-1))" /></q-page>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import ProcessPage from '@/app/process/pages/index.vue'
import ExternalProcessEditor from '@/app/process/components/ExternalProcessEditor.vue'
const route = useRoute()
</script>
