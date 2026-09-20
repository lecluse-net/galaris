<template>
  <PersonAvatar :name="name" :avatar-url="avatarUrl" :size="size" />
</template>

<script setup lang="ts">
import { PersonAvatar } from '@/core/util'

defineProps<{
  name: string
  avatarUrl?: string | null
  size?: string
}>()
</script>
