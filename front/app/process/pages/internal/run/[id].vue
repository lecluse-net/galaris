<template>
  <q-page>
    <NativeRunDialog :key="String(route.params.id)" :run-id="String(route.params.id)" @close="router.push('/process')" />
  </q-page>
</template>
<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import NativeRunDialog from '../../../components/NativeRunDialog.vue'
const route = useRoute()
const router = useRouter()
</script>
