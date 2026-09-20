<template>
  <div class="topic-assignment-editor">
    <TopicSelect
      v-model="draftTopicId"
      allow-create
      dense
      outlined
      hide-bottom-space
      :label="t('topic.assignment')"
      :disable="!editable || saving"
      class="topic-assignment-select"
    />
    <q-btn
      v-if="editable"
      class="topic-assignment-save"
      no-caps
      color="deep-purple"
      icon="save"
      :label="t('topic.saveAssignment')"
      :loading="saving"
      :disable="saving || !dirty"
      @click="emit('save', draftTopicId)"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import TopicSelect from './TopicSelect.vue'

const props = withDefaults(defineProps<{
  topicId: string | null
  editable?: boolean
  saving?: boolean
}>(), {
  editable: false,
  saving: false,
})

const emit = defineEmits<{
  save: [topicId: string | null]
}>()

const { t } = useI18n()
const draftTopicId = ref<string | null>(props.topicId)
const dirty = computed(() => draftTopicId.value !== props.topicId)

watch(() => props.topicId, value => {
  draftTopicId.value = value
})
</script>

<style scoped>
.topic-assignment-editor {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
  padding: 6px 16px;
}

.topic-assignment-select {
  flex: 1 1 0;
  min-width: 0;
}

.topic-assignment-save {
  flex: 0 0 auto;
  min-height: 40px;
}

@media (max-width: 1023px) {
  .topic-assignment-editor {
    align-items: stretch;
    flex-direction: column;
  }

  .topic-assignment-select {
    flex-basis: auto;
  }
}
</style>
