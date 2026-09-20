<template>
  <q-page />
</template>

<script setup lang="ts">
import { onBeforeMount } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

onBeforeMount(() => {
  void router.replace({
    path: '/task',
    query: { ...route.query, tab: 'llm' },
  })
})
</script>
