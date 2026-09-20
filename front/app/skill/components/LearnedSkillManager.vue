<template>
  <div class="q-pt-md">
    <q-banner rounded class="bg-blue-1 text-primary q-mb-md">
      {{ t('skills.learning.hint') }}
    </q-banner>

    <AgentSelect
      v-model="selectedAgentId"
      outlined
      dense
      clearable
      emit-value
      map-options
      :options="agentOptions"
      :label="t('skills.learning.agentFilter')"
      class="q-mb-md learned-agent-filter"
      @update:model-value="onAgentFilterChange"
    />

    <q-table
      flat
      bordered
      row-key="id"
      :rows="rows"
      :columns="columns"
      :loading="loading"
      :pagination="pagination"
      :rows-per-page-options="[10, 20, 50, 100, 500]"
      @request="onRequest"
    >
      <template #body-cell-agent="props">
        <q-td :props="props">
          <div>{{ agentLabel(props.row.agent_id) }}</div>
          <code class="text-caption text-grey-7">#{{ props.row.agent_id }}</code>
        </q-td>
      </template>

      <template #body-cell-skill="props">
        <q-td :props="props">
          <div class="text-weight-medium">{{ props.row.label }}</div>
          <code class="text-caption text-grey-7">{{ props.row.code }}</code>
          <div class="text-caption text-grey-7 q-mt-xs learned-description">
            {{ props.row.description }}
          </div>
        </q-td>
      </template>

      <template #body-cell-score="props">
        <q-td :props="props">
          <div class="row items-center no-wrap q-gutter-sm">
            <q-linear-progress
              rounded
              size="10px"
              :value="props.row.score"
              :color="props.row.injectable ? 'positive' : 'warning'"
              class="learned-score"
            />
            <span>{{ formatScore(props.row.score) }}</span>
          </div>
          <div class="text-caption text-grey-7">
            {{ t('skills.learning.evidenceCount', { count: props.row.evidence_count }) }}
          </div>
        </q-td>
      </template>

      <template #body-cell-status="props">
        <q-td :props="props">
          <q-chip
            dense
            :color="props.row.suspended ? 'grey' : props.row.injectable ? 'positive' : 'warning'"
            text-color="white"
            :icon="props.row.suspended ? 'pause_circle' : props.row.injectable ? 'check_circle' : 'school'"
          >
            {{ statusLabel(props.row) }}
          </q-chip>
        </q-td>
      </template>

      <template #body-cell-actions="props">
        <q-td :props="props">
          <q-btn flat round color="primary" icon="visibility" @click="openDetail(props.row.id)">
            <q-tooltip>{{ t('skills.view') }}</q-tooltip>
          </q-btn>
          <q-btn
            v-if="canEdit"
            flat
            round
            :color="props.row.suspended ? 'positive' : 'warning'"
            :icon="props.row.suspended ? 'play_arrow' : 'pause'"
            :loading="mutatingId === props.row.id"
            @click="setSuspended(props.row, !props.row.suspended)"
          >
            <q-tooltip>
              {{ props.row.suspended ? t('skills.learning.resume') : t('skills.learning.suspend') }}
            </q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="detailDialog">
      <q-card class="column no-wrap learned-detail-dialog">
        <q-toolbar class="galaris-dialog-title bg-primary text-white">
          <q-toolbar-title>{{ selected?.label || t('skills.learning.detail') }}</q-toolbar-title>
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('skills.cancel')" />
        </q-toolbar>
        <q-card-section v-if="detailLoading" class="row justify-center q-pa-xl">
          <q-spinner color="primary" size="42px" />
        </q-card-section>
        <template v-else-if="selected">
          <q-card-section>
            <div class="row q-col-gutter-md">
              <div class="col-6 col-md-3">
                <div class="text-caption text-grey-7">{{ t('skills.learning.score') }}</div>
                <div class="text-h6">{{ formatScore(selected.score) }}</div>
              </div>
              <div class="col-6 col-md-3">
                <div class="text-caption text-grey-7">{{ t('skills.learning.positive') }}</div>
                <div>{{ selected.positive_weight.toFixed(2) }}</div>
              </div>
              <div class="col-6 col-md-3">
                <div class="text-caption text-grey-7">{{ t('skills.learning.negative') }}</div>
                <div>{{ selected.negative_weight.toFixed(2) }}</div>
              </div>
              <div class="col-6 col-md-3">
                <div class="text-caption text-grey-7">{{ t('skills.learning.revision') }}</div>
                <div>{{ selected.revision }}</div>
              </div>
            </div>
          </q-card-section>
          <q-separator />
          <q-tabs v-model="detailTab" dense align="left" class="text-primary">
            <q-tab name="instructions" icon="description" :label="t('skills.learning.instructions')" />
            <q-tab name="evidence" icon="fact_check" :label="t('skills.learning.evidence')" />
          </q-tabs>
          <q-tab-panels v-model="detailTab" animated class="col scroll">
            <q-tab-panel name="instructions">
              <Markdown :content="selected.markdown" compact-frontmatter />
            </q-tab-panel>
            <q-tab-panel name="evidence">
              <q-list bordered separator>
                <q-item v-for="item in selected.evidences" :key="item.id">
                  <q-item-section>
                    <q-item-label>
                      <q-chip
                        dense
                        :color="item.polarity === 'positive' ? 'positive' : 'negative'"
                        text-color="white"
                      >
                        {{ item.operation }} · {{ item.weight.toFixed(2) }}
                      </q-chip>
                      <code class="text-caption q-ml-sm">{{ item.source_ref }}</code>
                    </q-item-label>
                    <q-item-label caption class="q-mt-sm">{{ item.rationale }}</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-tab-panel>
          </q-tab-panels>
        </template>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { QTableProps } from 'quasar'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'

import { privileges, usePrivilegeStore } from '@/core/authorize'
import { Markdown } from '@/core/util'
import { AgentSelect } from '@/app/agent'
import {
  skillService,
  type LearnedSkill,
  type LearnedSkillDetail,
  type SkillAgent,
} from '../services/skillService'

const $q = useQuasar()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.SKILL_EDIT))
const rows = ref<LearnedSkill[]>([])
const agents = ref<SkillAgent[]>([])
const selectedAgentId = ref<number | null>(null)
const loading = ref(false)
const mutatingId = ref<string | null>(null)
const detailLoading = ref(false)
const detailDialog = ref(false)
const detailTab = ref<'instructions' | 'evidence'>('instructions')
const selected = ref<LearnedSkillDetail | null>(null)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const agentOptions = computed(() => agents.value.map(agent => ({
  label: `${agent.label} (${agent.code})`,
  value: agent.id,
})))

const columns = computed<QTableProps['columns']>(() => [
  { name: 'agent', label: t('skills.learning.agent'), field: 'agent_id', align: 'left' },
  { name: 'skill', label: t('skills.learning.skill'), field: 'label', align: 'left' },
  { name: 'score', label: t('skills.learning.score'), field: 'score', align: 'left', sortable: true },
  { name: 'status', label: t('skills.status'), field: 'injectable', align: 'center' },
  { name: 'actions', label: t('skills.actions'), field: 'actions', align: 'right' },
])

function formatScore(score: number): string {
  return `${Math.round(score * 100)} %`
}

function statusLabel(skill: LearnedSkill): string {
  if (skill.suspended) return t('skills.learning.statuses.suspended')
  if (skill.injectable) return t('skills.learning.statuses.injected')
  return t('skills.learning.statuses.learning')
}

function agentLabel(agentId: number): string {
  return agents.value.find(agent => agent.id === agentId)?.label || t('skills.learning.unknownAgent')
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const response = await skillService.getLearnedSkills({
      agentId: selectedAgentId.value,
      page: pagination.value.page,
      pageSize: pagination.value.rowsPerPage,
    })
    rows.value = response.data.items
    pagination.value.rowsNumber = response.data.total
  } finally {
    loading.value = false
  }
}

async function onAgentFilterChange(): Promise<void> {
  pagination.value.page = 1
  await load()
}

async function onRequest(request: { pagination: { page: number; rowsPerPage: number } }): Promise<void> {
  pagination.value.page = request.pagination.page
  pagination.value.rowsPerPage = request.pagination.rowsPerPage
  await load()
}

async function openDetail(id: string): Promise<void> {
  detailDialog.value = true
  detailLoading.value = true
  selected.value = null
  try {
    selected.value = (await skillService.getLearnedSkill(id)).data
  } finally {
    detailLoading.value = false
  }
}

async function setSuspended(skill: LearnedSkill, suspended: boolean): Promise<void> {
  mutatingId.value = skill.id
  try {
    const result = (await skillService.setLearnedSkillSuspended(skill.id, suspended)).data
    await Promise.all(result.affected_agent_ids.map(agentId => skillService.syncAgent(agentId)))
    const index = rows.value.findIndex(item => item.id === result.skill.id)
    if (index !== -1) rows.value.splice(index, 1, result.skill)
    $q.notify({ type: 'positive', message: t('skills.learning.updated') })
  } finally {
    mutatingId.value = null
  }
}

onMounted(async () => {
  const response = await skillService.getAgents()
  agents.value = response.data
  await load()
})
</script>

<style scoped>
.learned-description {
  max-width: 540px;
  white-space: normal;
}

.learned-score {
  width: 120px;
}

.learned-agent-filter {
  max-width: 420px;
}

.learned-detail-dialog {
  width: 900px;
  max-width: 95vw;
  height: 760px;
  max-height: 90vh;
}
</style>
