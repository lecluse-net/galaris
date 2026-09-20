<template>
  <div class="row items-center q-gutter-sm">
    <q-badge color="primary" :label="team.human_count" />
    <template v-if="team.human_count <= 3">
      <span v-for="member in team.human_members" :key="member.id" class="row items-center no-wrap q-gutter-xs">
        <UserAvatar :name="member.label" :avatar-url="member.avatar_url" size="28px" />
        <span>{{ member.label }}</span>
      </span>
    </template>
  </div>
</template>

<script setup lang="ts">
import { UserAvatar } from '@/core/user'
import type { Team } from '../services/teamService'
defineProps<{ team: Team }>()
</script>
