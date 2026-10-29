<template>
  <div class="personal-status">
    <q-chip dense :icon="skill.enabled ? 'check_circle' : 'pause_circle'"
      class="activation-chip" :class="skill.enabled ? 'activation-chip--enabled' : 'activation-chip--disabled'">
      {{ t(skill.enabled ? 'skills.personal.enabled' : 'skills.personal.disabled') }}
    </q-chip>
    <q-chip v-if="skill.learning" dense icon="school" class="activation-chip--disabled">
      {{ t(skill.learning.qualified ? 'skills.learning.qualified' : 'skills.learning.candidate') }}
      <q-tooltip>{{ t('skills.learning.summary', { count: skill.learning.evidence_count, score: Math.round(skill.learning.score * 100) }) }}</q-tooltip>
    </q-chip>
    <q-chip v-if="!skill.available || !skill.valid" dense class="validity-chip"
      :icon="!skill.available ? 'folder_off' : 'warning'">
      {{ t(!skill.available ? 'skills.missing' : 'skills.invalid') }}
    </q-chip>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { PersonalSkill } from '../services/skillService'
defineProps<{ skill: PersonalSkill }>()
const { t } = useI18n()
</script>

<style scoped>
.personal-status { display: flex; flex-wrap: wrap; gap: 4px; }
.personal-status .q-chip { margin: 0; max-width: 100%; height: auto; min-height: 2em; font-weight: 600; color: inherit; }
.personal-status :deep(.q-chip__content) { white-space: normal; min-width: 0; overflow-wrap: anywhere; }
.activation-chip :deep(.q-chip__content) { white-space: nowrap; overflow-wrap: normal; }
.activation-chip--enabled { background: var(--solaire-green-light); border: 1px solid var(--solaire-green-accent); }
.activation-chip--enabled :deep(.q-chip__icon) { color: var(--solaire-green-accent); }
.activation-chip--disabled { background: var(--solaire-gray-light); border: 1px solid var(--solaire-gray-accent); }
.activation-chip--disabled :deep(.q-chip__icon) { color: var(--solaire-gray-accent); }
.validity-chip { background: var(--solaire-red-light); border: 1px solid var(--solaire-red-accent); }
.validity-chip :deep(.q-chip__icon) { color: var(--solaire-red-accent); }
.body--dark .activation-chip--enabled { background: var(--solaire-green-dark); }
.body--dark .activation-chip--disabled { background: var(--solaire-gray-dark); }
.body--dark .validity-chip { background: var(--solaire-red-dark); }
</style>
