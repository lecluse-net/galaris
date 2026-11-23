<template>
  <div v-for="group in groups" :key="group.key" role="group" :aria-label="t(`nativeProcesses.activityGroups.${group.key}`)">
    <q-item-label header>{{ t(`nativeProcesses.activityGroups.${group.key}`) }}</q-item-label>
    <q-item v-for="kind in group.kinds" :key="kind" clickable v-close-popup
      :disable="(kind === 'human_task' || kind === 'if_human') && !hasHumanActor" @click="emit('select', kind)">
      <q-item-section avatar><q-icon :name="nodeIcons[activityNodeKind(kind)]" /></q-item-section>
      <q-item-section>{{ t(activityLabelKey(kind, typed)) }}</q-item-section>
    </q-item>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { activityGroups, activityNodeKind, activityLabelKey, nodeIcons, waitKinds, type ActivityKind } from '../graphEditing'

const props = withDefaults(defineProps<{ typed: boolean; hasHumanActor: boolean; allowEnd?: boolean; waitsOnly?: boolean }>(), { allowEnd: true })
const emit = defineEmits<{ select: [kind: ActivityKind] }>()
const { t } = useI18n()

const typedOnly: ActivityKind[] = ['if_code', 'if_llm', 'if_human', 'llm_task', 'python', 'rest', 'event_choice', ...waitKinds]
const groups = computed(() => activityGroups.map(group => ({ ...group, kinds: group.kinds.filter(kind =>
  (kind !== 'end' || props.allowEnd) && (props.typed ? kind !== 'if' : !typedOnly.includes(kind))
  && (!props.waitsOnly || waitKinds.includes(activityNodeKind(kind))),
) })).filter(group => group.kinds.length > 0))
</script>
