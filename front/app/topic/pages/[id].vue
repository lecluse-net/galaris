<template><TopicDetail :topic-id="String(route.params.id || '')" /></template>
<script setup lang="ts">
import { useRoute } from 'vue-router'
import TopicDetail from '../components/TopicDetail.vue'
const route = useRoute()
</script>
