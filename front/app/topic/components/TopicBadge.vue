<template>
  <button
    type="button"
    class="topic-badge-shell"
    :aria-label="t('topic.assignmentAudit.open', { title: displayTitle })"
    @click.stop="openAssignmentAudit"
  >
    <q-badge outline color="deep-purple" class="topic-badge no-wrap">
      <q-icon name="folder" size="10px" class="q-mr-xs" />
      <span class="topic-badge-title ellipsis">{{ displayTitle }}</span>
    </q-badge>
    <q-tooltip>{{ displayTitle }}</q-tooltip>
  </button>

  <q-dialog v-model="auditOpen">
    <q-card class="topic-assignment-audit-card">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <q-icon name="rule_folder" size="22px" class="q-mr-sm" />
        <div class="text-h6 ellipsis">{{ t('topic.assignmentAudit.title') }}</div>
        <q-space />
        <q-btn
          v-close-popup
          flat
          round
          dense
          icon="close"
          :aria-label="t('topic.assignmentAudit.close')"
        />
      </q-card-section>

      <q-separator />

      <q-card-section v-if="auditLoading" class="row justify-center q-pa-xl">
        <q-spinner color="primary" size="36px" />
      </q-card-section>

      <q-card-section v-else-if="auditError">
        <q-banner rounded class="bg-red-1 text-negative">
          <q-icon name="error_outline" class="q-mr-xs" />
          {{ auditError }}
        </q-banner>
      </q-card-section>

      <template v-else-if="audit">
        <q-card-section>
          <div class="row items-center q-gutter-sm q-mb-md">
            <q-badge outline color="deep-purple" class="topic-badge no-wrap">
              <q-icon name="folder" size="12px" class="q-mr-xs" />
              {{ displayTitle }}
            </q-badge>
            <q-chip
              dense
              :color="audit.origin === 'dream' ? 'primary' : 'grey-7'"
              text-color="white"
              :icon="audit.origin === 'dream' ? 'bedtime' : 'person'"
            >
              {{ t(`topic.assignmentAudit.origins.${audit.origin}`) }}
            </q-chip>
            <q-chip v-if="audit.human_confirmed" dense outline color="secondary" icon="how_to_reg">
              {{ t('topic.assignmentAudit.humanConfirmed') }}
            </q-chip>
          </div>

          <template v-if="audit.origin === 'dream'">
            <div class="topic-assignment-field">
              <div class="text-caption text-grey-7">{{ t('topic.assignmentAudit.action') }}</div>
              <div class="text-weight-medium">
                {{ audit.action ? t(`topic.assignmentAudit.actions.${audit.action}`) : t('topic.assignmentAudit.unknownAction') }}
              </div>
            </div>
            <div class="topic-assignment-field">
              <div class="text-caption text-grey-7">{{ t('topic.assignmentAudit.reason') }}</div>
              <div>{{ audit.reason || t('topic.assignmentAudit.noReason') }}</div>
            </div>
            <div v-if="audit.confidence !== null" class="topic-assignment-field">
              <div class="text-caption text-grey-7">{{ t('topic.assignmentAudit.confidence') }}</div>
              <div>{{ formatConfidence(audit.confidence) }}</div>
            </div>
            <div v-if="audit.decided_at" class="topic-assignment-field">
              <div class="text-caption text-grey-7">{{ t('topic.assignmentAudit.decidedAt') }}</div>
              <div>{{ formatDate(audit.decided_at) }}</div>
            </div>
            <div v-if="audit.dream_receipt_id" class="topic-assignment-field">
              <div class="text-caption text-grey-7">{{ t('topic.assignmentAudit.dreamAction') }}</div>
              <div class="text-mono text-caption">{{ audit.dream_receipt_id }}</div>
            </div>
          </template>

          <q-banner v-else rounded class="bg-grey-2 text-grey-8">
            <q-icon name="person" class="q-mr-xs" />
            {{ t('topic.assignmentAudit.manualHint') }}
          </q-banner>
        </q-card-section>

        <template v-if="canReassignTopic">
          <q-separator />
          <q-card-section class="topic-reassignment">
            <div class="text-subtitle2 q-mb-sm">
              {{ t('topic.assignmentAudit.changeTopic') }}
            </div>
            <TopicSelect
              :key="subjectId"
              v-model="selectedTopicId"
              allow-create
              :label="t('topic.assignment')"
              :clearable="false"
              :disable="topicChangeLoading"
            />
            <q-banner
              v-if="topicChangeError"
              rounded
              class="bg-red-1 text-negative q-mt-sm"
            >
              <q-icon name="error_outline" class="q-mr-xs" />
              {{ topicChangeError }}
            </q-banner>
            <div class="topic-reassignment-actions q-mt-md">
              <q-btn
                outline
                no-caps
                color="primary"
                icon="edit"
                :label="t('topic.assignmentAudit.changeThisMessage')"
                :disable="!canSubmitTopicChange"
                :loading="topicChangeLoading && topicChangeScope === 'message'"
                @click="changeTopic('message')"
              />
              <q-btn
                unelevated
                no-caps
                color="primary"
                icon="playlist_add_check"
                :label="t('topic.assignmentAudit.changeFollowingSameTopic')"
                :disable="!canSubmitTopicChange"
                :loading="topicChangeLoading && topicChangeScope === 'following_same_topic'"
                @click="changeTopic('following_same_topic')"
              />
            </div>
          </q-card-section>
        </template>

        <q-separator />

        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn
            v-if="canOpenTopic"
            flat
            no-caps
            color="deep-purple"
            icon="folder_open"
            :label="t('topic.assignmentAudit.openTopic')"
            @click="openTopic"
          />
          <q-btn
            v-if="audit.dream_receipt_id && canOpenDream"
            unelevated
            no-caps
            color="primary"
            icon="bedtime"
            :label="t('topic.assignmentAudit.openDreamAction')"
            @click="openDreamAction(audit.dream_receipt_id)"
          />
        </q-card-actions>
      </template>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { privileges } from '@/core/authorize'
import { usePrivilegeStore } from '@/core/authorize/stores/privilegeStore'
import { topicService } from '../services/topicService'
import TopicSelect from './TopicSelect.vue'
import type {
  TopicAssignmentAudit,
  TopicAssignmentChangeScope,
  TopicAssignmentSubjectKind,
} from '../types'

const props = withDefaults(defineProps<{
  topicId: string
  title?: string
  subjectKind?: TopicAssignmentSubjectKind
  subjectId?: string
  allowTopicChange?: boolean
  reassignTopic?: (
    topicId: string,
    scope: TopicAssignmentChangeScope,
  ) => Promise<number>
}>(), {
  allowTopicChange: true,
  reassignTopic: undefined,
})

const { t } = useI18n()
const router = useRouter()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const auditOpen = ref(false)
const auditLoading = ref(false)
const auditError = ref('')
const audit = ref<TopicAssignmentAudit | null>(null)
const selectedTopicId = ref<string | null>(props.topicId)
const topicChangeLoading = ref(false)
const topicChangeError = ref('')
const topicChangeScope = ref<TopicAssignmentChangeScope | null>(null)
const canOpenTopic = computed(() => (
  privilegeStore.hasPrivilege(privileges.TOPIC_ACCESS)
  || privilegeStore.hasPrivilege(privileges.TOPIC_EDIT)
))
const canOpenDream = computed(() => privilegeStore.hasPrivilege(privileges.TASK_ACCESS))
const canReassignTopic = computed(() => (
  props.allowTopicChange
  && props.subjectKind === 'message'
  && Boolean(props.reassignTopic)
  && privilegeStore.hasPrivilege(privileges.TOPIC_EDIT)
))
const canSubmitTopicChange = computed(() => (
  Boolean(selectedTopicId.value)
  && selectedTopicId.value !== props.topicId
  && !topicChangeLoading.value
))
const displayTitle = computed(() => props.title?.trim() || t('topic.unnamedBadge'))

async function openAssignmentAudit(): Promise<void> {
  if (!props.subjectKind || !props.subjectId) {
    openTopic()
    return
  }
  auditOpen.value = true
  auditLoading.value = true
  auditError.value = ''
  audit.value = null
  selectedTopicId.value = props.topicId
  topicChangeError.value = ''
  topicChangeScope.value = null
  try {
    audit.value = await topicService.assignmentAudit({
      topicId: props.topicId,
      subjectKind: props.subjectKind,
      subjectId: props.subjectId,
    })
  } catch (error) {
    auditError.value = apiErrorDetail(error) ?? t('topic.assignmentAudit.loadError')
  } finally {
    auditLoading.value = false
  }
}

async function changeTopic(scope: TopicAssignmentChangeScope): Promise<void> {
  if (!selectedTopicId.value || !canSubmitTopicChange.value || !props.reassignTopic) return
  topicChangeLoading.value = true
  topicChangeScope.value = scope
  topicChangeError.value = ''
  try {
    const updated = await props.reassignTopic(selectedTopicId.value, scope)
    auditOpen.value = false
    $q.notify({
      type: 'positive',
      message: t('topic.assignmentAudit.changeSuccess', { count: updated }),
    })
  } catch (error) {
    topicChangeError.value = apiErrorDetail(error)
      ?? t('topic.assignmentAudit.changeError')
  } finally {
    topicChangeLoading.value = false
    topicChangeScope.value = null
  }
}

function openTopic(): void {
  if (!canOpenTopic.value) return
  auditOpen.value = false
  void router.push(`/topic/${encodeURIComponent(props.topicId)}`)
}

function openDreamAction(receiptId: string): void {
  auditOpen.value = false
  void router.push({ path: '/dream', query: { receipt_id: receiptId } })
}

function formatConfidence(value: number): string {
  return new Intl.NumberFormat(undefined, {
    style: 'percent',
    maximumFractionDigits: 0,
  }).format(value)
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(value))
}
</script>

<style scoped>
.topic-badge-shell {
  display: inline-flex;
  min-width: 0;
  max-width: min(100%, 32rem);
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  vertical-align: middle;
}

.topic-badge-shell {
  cursor: pointer;
}

.topic-badge-shell:focus-visible {
  border-radius: 4px;
  outline: 2px solid var(--q-primary);
  outline-offset: 1px;
}

.topic-badge {
  min-width: 0;
  max-width: 100%;
  padding: 1px 5px;
  font-size: 10px;
  font-weight: 500;
  line-height: 1.25;
}

.topic-reassignment-actions {
  display: flex;
  align-items: stretch;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.topic-reassignment-actions :deep(.q-btn) {
  min-height: 38px;
}

@media (max-width: 599px) {
  .topic-reassignment-actions :deep(.q-btn) {
    width: 100%;
  }
}

.topic-badge-title {
  min-width: 0;
}

.topic-assignment-audit-card {
  width: min(94vw, 620px);
  max-width: 620px;
}

.topic-assignment-field + .topic-assignment-field {
  margin-top: 14px;
}
</style>
