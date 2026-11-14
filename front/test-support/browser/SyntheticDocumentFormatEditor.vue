<template><q-input v-model="model" outlined type="textarea" :readonly="readonly" aria-label="Synthetic format content" /></template>
<script setup lang="ts">
const model = defineModel<string>({ required: true })
defineProps<{ readonly?: boolean }>()
</script>
