<template>
  <TopicBadge :topic-id="topicId" :title="topicTitle(topicId)" :subject-kind="kind" :subject-id="id"
    :allow-topic-change="editable" :reassign-topic="reassignTopic" size="regular" />
</template>

<script lang="ts">
import { topicService } from '@/app/topic/interface'
export async function reassignResourceTopic(kind: 'document' | 'dataset', id: string, topicId: string,
  expectedTopicId: string | null, expectedLockVersion: number): Promise<{ topic_id: string; lock_version: number }> {
  return await topicService.reassignResource(kind, id, topicId, expectedTopicId, expectedLockVersion)
}
</script>

<script setup lang="ts">
import { watch } from 'vue'
import { TopicBadge, useTopicRefs } from '@/app/topic'

const props = defineProps<{
  kind: 'document' | 'dataset'
  id: string
  topicId: string | null
  editable: boolean
  reassignTopic: (topicId: string) => Promise<number>
}>()
const { topicTitle, resolveTopicRefs } = useTopicRefs()
watch(() => props.topicId, id => { void resolveTopicRefs([id]) }, { immediate: true })
</script>
