<template>
  <div v-if="groups.length" class="topic-relations q-gutter-y-xs">
    <div v-for="group in groups" :key="group.key" class="topic-relation-group">
      <div class="topic-relation-label">{{ group.label }}</div>
      <div class="row q-gutter-xs">
        <q-btn
          v-if="group.items.length > 5"
          dense
          flat
          no-caps
          :icon="group.icon"
          :label="group.countLabel"
          :style="group.style"
        >
          <q-menu max-height="320px">
            <q-list>
              <q-item v-for="item in group.items" :key="item.id">
                <q-item-section>{{ item.name }}</q-item-section>
              </q-item>
            </q-list>
          </q-menu>
        </q-btn>
        <template v-else>
          <q-chip
            v-for="item in group.items"
            :key="item.id"
            dense
            :icon="group.icon"
            :style="group.style"
            :title="item.name"
          >
            {{ item.name }}
          </q-chip>
        </template>
      </div>
    </div>
  </div>
  <span v-else class="text-grey-6">{{ t('topic.noRelations') }}</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { solaireCss } from '@/core/util'
import type { TopicMonthlyUsage } from '../types'

const props = defineProps<{ topic: Pick<TopicMonthlyUsage, 'agents' | 'users' | 'teams'> }>()
const { t } = useI18n()
const $q = useQuasar()
const groups = computed(() => [
  { key: 'agents', icon: 'smart_toy', color: 'blue' as const, items: props.topic.agents },
  { key: 'users', icon: 'person', color: 'violet' as const, items: props.topic.users.map(user => ({ id: user.id, name: user.display_name })) },
  { key: 'teams', icon: 'groups', color: 'green' as const, items: props.topic.teams },
].filter(group => group.items.length).map(group => ({
  ...group,
  label: t(`topic.${group.key}`),
  countLabel: t(`topic.participantCounts.${group.key}`, { count: group.items.length }),
  style: { background: solaireCss[group.color][$q.dark.isActive ? 'dark' : 'light'], '--participant-accent': solaireCss[group.color].accent },
})))
</script>

<style scoped>
.topic-relations,
.topic-relation-group {
  min-width: 0;
}

.topic-relation-label {
  font-size: 0.7rem;
  font-weight: 650;
  line-height: 1.2;
  text-transform: uppercase;
}

.q-chip {
  max-width: 100%;
}

.q-chip :deep(.q-chip__content) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.q-icon) {
  color: var(--participant-accent);
}
</style>
