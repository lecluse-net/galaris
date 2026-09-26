<template>
  <div>
    <q-banner class="bg-grey-2 text-grey-8 q-mb-md" dense rounded>
      <template #avatar>
        <q-icon name="shield" color="primary" />
      </template>
      {{ t('skills.auth.intro') }}
    </q-banner>

    <div class="row items-center q-col-gutter-md q-mb-md">
      <div class="col-12">
        <span class="text-subtitle2 text-primary text-weight-bold section-label">
          <q-icon name="filter_alt" size="xs" class="q-mr-xs" />
          {{ t('skills.auth.filters') }}
        </span>
      </div>
      <div class="col-12 col-md-3">
        <AgentSelect
          v-model="filterAgentId"
          :options="agentOptions"
          :label="t('skills.auth.selectAgent')"
          dense
          outlined
          clearable
          emit-value
          map-options
          :loading="store.loading"
        />
      </div>
      <div class="col-12 col-md-3">
        <q-select
          v-model="filterSkillId"
          :options="skillOptions"
          :label="t('skills.auth.selectSkill')"
          dense
          outlined
          clearable
          emit-value
          map-options
          :loading="store.loading"
        />
      </div>
      <div class="col-12 col-md-3">
        <q-select
          v-model="filterCategoryId"
          :options="categoryOptions"
          :label="t('skills.auth.selectCategory')"
          dense
          outlined
          clearable
          emit-value
          map-options
          :loading="store.loading"
        />
      </div>
      <div class="col-12 col-md-3">
        <q-btn-toggle
          v-model="filterState"
          :options="stateFilterOptions"
          color="grey-4"
          text-color="grey-8"
          toggle-color="primary"
          spread
          unelevated
          no-caps
          class="full-width"
        />
      </div>
    </div>

    <q-banner v-if="loadError" class="bg-negative text-white q-mb-md" dense rounded>
      <template #avatar><q-icon name="error" /></template>
      {{ loadError }}
    </q-banner>

    <div v-if="loading && groupedAuthorizations.length === 0" class="row justify-center q-pa-xl">
      <q-spinner color="primary" size="42px" />
    </div>
    <div v-else-if="groupedAuthorizations.length > 0">
      <section
        v-for="group in groupedAuthorizations"
        :key="group.key"
        class="q-mb-lg"
      >
        <div class="row items-center q-gutter-sm q-mb-sm authorization-category-heading">
          <q-icon name="category" color="primary" size="sm" />
          <div class="text-h6">{{ group.label }}</div>
          <q-badge color="primary" :label="group.skillCount" />
        </div>
        <q-table
          :rows="group.authorizations"
          :columns="columns"
          :row-key="authorizationRowKey"
          :loading="loading"
          :pagination="defaultPagination"
          :rows-per-page-options="[10, 20, 50, 100, 500]"
          :grid="$q.screen.lt.md"
          class="authorization-table"
          flat
          bordered
        >
      <template #body-cell-skill="props">
        <q-td :props="props">
          <div class="text-weight-medium">{{ props.row.label }}</div>
          <code class="text-caption text-grey-7">{{ props.row.code }}</code>
        </q-td>
      </template>
      <template #body-cell-agentIdentity="props">
        <q-td :props="props">
          <div class="row items-center no-wrap q-gutter-sm">
            <AgentAvatar
              :agent-id="props.row.agent_id"
              :name="props.row.agent_label"
              size="36px"
            />
            <div class="col agent-identity-text">
              <div class="text-weight-medium ellipsis" :title="props.row.agent_label">
                {{ props.row.agent_label }}
              </div>
              <code class="text-caption text-grey-7 ellipsis block">
                {{ props.row.agent_code }}
              </code>
            </div>
          </div>
        </q-td>
      </template>
      <template #body-cell-description="props">
        <q-td :props="props">
          <span class="text-grey-8">{{ props.row.description || '—' }}</span>
        </q-td>
      </template>
      <template #body-cell-global="props">
        <q-td :props="props" class="text-center">
          <q-btn-toggle
            v-if="canAssign && canManageAllAgents"
            :model-value="props.row.global_state"
            :options="globalStateOptions"
            color="grey-4"
            text-color="grey-8"
            toggle-color="primary"
            dense
            unelevated
            no-caps
            @update:model-value="onGlobalState(props.row, $event)"
          />
        </q-td>
      </template>
      <template #body-cell-category="props">
        <q-td :props="props" class="text-center">
          <q-btn-toggle
            :model-value="props.row.category_state"
            :options="agentStateOptions"
            color="grey-4"
            text-color="grey-8"
            toggle-color="primary"
            dense
            unelevated
            no-caps
            :disable="!canAssign || props.row.category_id === null"
            @update:model-value="onCategoryState(props.row, $event)"
          />
        </q-td>
      </template>
      <template #body-cell-agent="props">
        <q-td :props="props" class="text-center">
          <q-btn-toggle
            v-if="canAssign"
            :model-value="props.row.agent_state"
            :options="agentStateOptions"
            color="grey-4"
            text-color="grey-8"
            toggle-color="primary"
            dense
            unelevated
            no-caps
            @update:model-value="onAgentState(props.row, $event)"
          />
        </q-td>
      </template>
      <template #body-cell-effective="props">
        <q-td :props="props" class="text-center">
          <q-icon
            :name="props.row.effective ? 'check_circle' : 'block'"
            :color="props.row.effective ? 'positive' : 'grey-5'"
            size="sm"
          >
            <q-tooltip>
              {{ props.row.effective ? t('skills.auth.effectiveOn') : t('skills.auth.effectiveOff') }}
            </q-tooltip>
          </q-icon>
        </q-td>
      </template>
      <template #item="props">
        <div class="q-table__grid-item col-12 authorization-grid-item">
          <q-card flat bordered class="authorization-mobile-card">
            <q-card-section class="q-gutter-md">
              <div class="row items-start no-wrap q-gutter-sm">
                <div class="col authorization-mobile-copy">
                  <div class="text-subtitle1 text-weight-medium">{{ props.row.label }}</div>
                  <code class="text-caption text-grey-7 authorization-mobile-code">
                    {{ props.row.code }}
                  </code>
                </div>
                <q-chip
                  dense
                  outline
                  :icon="props.row.effective ? 'check_circle' : 'block'"
                  :color="props.row.effective ? 'positive' : 'grey-6'"
                >
                  {{ props.row.effective ? t('skills.auth.effectiveOn') : t('skills.auth.effectiveOff') }}
                </q-chip>
              </div>

              <div>
                <div class="authorization-mobile-label">{{ t('skills.auth.colAgentIdentity') }}</div>
                <div class="row items-center no-wrap q-gutter-sm q-mt-xs">
                  <AgentAvatar
                    :agent-id="props.row.agent_id"
                    :name="props.row.agent_label"
                    size="36px"
                  />
                  <div class="col authorization-mobile-copy">
                    <div class="text-weight-medium">{{ props.row.agent_label }}</div>
                    <code class="text-caption text-grey-7 authorization-mobile-code">
                      {{ props.row.agent_code }}
                    </code>
                  </div>
                </div>
              </div>

              <div>
                <div class="authorization-mobile-label">{{ t('skills.auth.colDescription') }}</div>
                <div class="q-mt-xs authorization-mobile-description">
                  {{ props.row.description || '—' }}
                </div>
              </div>

              <div class="authorization-mobile-controls">
                <div>
                  <div class="authorization-mobile-label q-mb-xs">{{ t('skills.auth.colGlobal') }}</div>
                  <q-btn-toggle
                    v-if="canAssign && canManageAllAgents"
                    :model-value="props.row.global_state"
                    :options="globalStateOptions"
                    color="grey-4"
                    text-color="grey-8"
                    toggle-color="primary"
                    dense
                    spread
                    unelevated
                    no-caps
                    class="full-width"
                    @update:model-value="onGlobalState(props.row, $event)"
                  />
                </div>

                <div>
                  <div class="authorization-mobile-label q-mb-xs">{{ t('skills.auth.colCategory') }}</div>
                  <q-btn-toggle
                    :model-value="props.row.category_state"
                    :options="agentStateOptions"
                    color="grey-4"
                    text-color="grey-8"
                    toggle-color="primary"
                    dense
                    spread
                    unelevated
                    no-caps
                    class="full-width"
                    :disable="!canAssign || props.row.category_id === null"
                    @update:model-value="onCategoryState(props.row, $event)"
                  />
                </div>

                <div>
                  <div class="authorization-mobile-label q-mb-xs">{{ t('skills.auth.colAgent') }}</div>
                  <q-btn-toggle
                    v-if="canAssign"
                    :model-value="props.row.agent_state"
                    :options="agentStateOptions"
                    color="grey-4"
                    text-color="grey-8"
                    toggle-color="primary"
                    dense
                    spread
                    unelevated
                    no-caps
                    class="full-width"
                    @update:model-value="onAgentState(props.row, $event)"
                  />
                </div>
              </div>
            </q-card-section>
          </q-card>
        </div>
      </template>
        </q-table>
      </section>
    </div>
    <div v-else class="text-center text-grey-7 q-pa-xl">
      {{ t('skills.auth.noSkills') }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { QTableProps } from 'quasar'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import AgentAvatar from '@/app/agent/components/AgentAvatar.vue'
import { AgentSelect } from '@/app/agent'
import { useAgentStore } from '@/app/agent/stores/agentStore'

import {
  skillService,
  type SkillAuthorization,
  type SkillAuthorizationResult,
  type SkillAuthorizationState,
  type SkillCategoryAuthorizationResult,
  type SkillCategoryAuthorizationState,
  type SkillGlobalAuthorizationState,
} from '../services/skillService'
import { useSkillStore } from '../stores/skillStore'

type FilterState = 'active' | 'inactive' | 'all'
interface AuthorizationGroup {
  key: string
  label: string
  skillCount: number
  authorizations: SkillAuthorization[]
}

const SESSION_AGENT_KEY = 'skill_authorization_agent_id'
const SESSION_SKILL_KEY = 'skill_authorization_skill_id'
const SESSION_CATEGORY_KEY = 'skill_authorization_category_id'

const $q = useQuasar()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const canAssign = computed(() => privilegeStore.hasPrivilege(privileges.SKILL_ASSIGN))
const canManageAllAgents = computed(() => (
  privilegeStore.hasPrivilege(privileges.AGENT_MANAGE_ALL)
))
const agentStore = useAgentStore()
const store = useSkillStore()

const filterAgentId = ref<number | null>(null)
const filterSkillId = ref<number | null>(null)
const filterCategoryId = ref<number | null>(null)
const authorizations = ref<SkillAuthorization[]>([])
const filterState = ref<FilterState>('all')
const loading = ref(false)
const loadError = ref<string | null>(null)
const ready = ref(false)
const defaultPagination = { page: 1, rowsPerPage: 50 }

const agentOptions = computed(() =>
  store.agents.map(agent => ({ label: `${agent.label} (${agent.code})`, value: agent.id }))
)

const skillOptions = computed(() =>
  store.skills.map(skill => ({ label: `${skill.label} (${skill.code})`, value: skill.id }))
)

const categoryOptions = computed(() =>
  store.categories.map(category => ({ label: category.label, value: category.id }))
)

const globalStateOptions = computed(() => [
  { label: t('skills.auth.globalActive'), value: 'enabled' as SkillGlobalAuthorizationState },
  { label: t('skills.auth.globalBlocked'), value: 'disabled' as SkillGlobalAuthorizationState },
])

const agentStateOptions = computed(() => [
  { label: t('skills.auth.stateDefault'), value: 'default' as SkillAuthorizationState },
  { label: t('skills.auth.stateEnabled'), value: 'enabled' as SkillAuthorizationState },
  { label: t('skills.auth.stateDisabled'), value: 'disabled' as SkillAuthorizationState },
])

const stateFilterOptions = computed(() => [
  { label: t('skills.auth.filterActive'), value: 'active' as FilterState },
  { label: t('skills.auth.filterInactive'), value: 'inactive' as FilterState },
  { label: t('skills.auth.filterAll'), value: 'all' as FilterState },
])

const filteredAuthorizations = computed(() => {
  let result = authorizations.value
  if (filterState.value !== 'all') {
    const active = filterState.value === 'active'
    result = result.filter(item => item.effective === active)
  }
  return result
})

const groupedAuthorizations = computed<AuthorizationGroup[]>(() => {
  const authorizationsByCategory = new Map<number | null, SkillAuthorization[]>()
  for (const authorization of filteredAuthorizations.value) {
    const rows = authorizationsByCategory.get(authorization.category_id) ?? []
    rows.push(authorization)
    authorizationsByCategory.set(authorization.category_id, rows)
  }

  const groups = store.categories.flatMap(category => {
    const authorizations = authorizationsByCategory.get(category.id)
    if (!authorizations?.length) return []
    authorizationsByCategory.delete(category.id)
    return [{
      key: `category-${category.id}`,
      label: category.label,
      skillCount: new Set(authorizations.map(item => item.skill_id)).size,
      authorizations,
    }]
  })

  for (const [categoryId, authorizations] of authorizationsByCategory) {
    if (categoryId === null) continue
    groups.push({
      key: `category-${categoryId}`,
      label: authorizations[0]?.category_label || t('skills.categories.none'),
      skillCount: new Set(authorizations.map(item => item.skill_id)).size,
      authorizations,
    })
  }

  const uncategorized = authorizationsByCategory.get(null)
  if (uncategorized?.length) {
    groups.push({
      key: 'uncategorized',
      label: t('skills.categories.none'),
      skillCount: new Set(uncategorized.map(item => item.skill_id)).size,
      authorizations: uncategorized,
    })
  }
  return groups
})

const columns = computed<QTableProps['columns']>(() => [
  {
    name: 'skill',
    label: t('skills.auth.colSkill'),
    field: 'label',
    align: 'left',
    sortable: true,
    style: 'width: 15%;',
    headerStyle: 'width: 15%;',
  },
  {
    name: 'agentIdentity',
    label: t('skills.auth.colAgentIdentity'),
    field: 'agent_label',
    align: 'left',
    sortable: true,
    style: 'width: 15%;',
    headerStyle: 'width: 15%;',
  },
  {
    name: 'description',
    label: t('skills.auth.colDescription'),
    field: 'description',
    align: 'left',
    style: 'width: 26%;',
    headerStyle: 'width: 26%;',
  },
  {
    name: 'global',
    label: t('skills.auth.colGlobal'),
    field: 'global_state',
    align: 'center',
    style: 'width: 10%;',
    headerStyle: 'width: 10%;',
  },
  {
    name: 'category',
    label: t('skills.auth.colCategory'),
    field: 'category_state',
    align: 'center',
    style: 'width: 13%;',
    headerStyle: 'width: 13%;',
  },
  {
    name: 'agent',
    label: t('skills.auth.colAgent'),
    field: 'agent_state',
    align: 'center',
    style: 'width: 13%;',
    headerStyle: 'width: 13%;',
  },
  {
    name: 'effective',
    label: t('skills.auth.colEffective'),
    field: 'effective',
    align: 'center',
    sortable: true,
    style: 'width: 8%;',
    headerStyle: 'width: 8%;',
  },
])

function authorizationRowKey(row: SkillAuthorization): string {
  return `${row.skill_id}:${row.agent_id}`
}

async function loadAuthorizations(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    authorizations.value = (
      await skillService.getAuthorizations(
        filterAgentId.value,
        filterSkillId.value,
        filterCategoryId.value,
      )
    ).data.authorizations
  } catch (error) {
    console.error('Error loading skill authorizations:', error)
    loadError.value = t('skills.auth.loadError')
    authorizations.value = []
  } finally {
    loading.value = false
  }
}

function applyResult(row: SkillAuthorization, result: SkillAuthorizationResult): void {
  Object.assign(row, {
    global_state: result.global_state,
    category_state: result.category_state,
    agent_state: result.agent_state,
    effective: result.effective,
  })
}

function inheritedEffective(authorization: SkillAuthorization): boolean {
  const enabled = authorization.category_state === 'default'
    ? authorization.global_state === 'enabled'
    : authorization.category_state === 'enabled'
  return enabled && authorization.available && authorization.valid
}

function applyGlobalResult(result: SkillAuthorizationResult): void {
  for (const authorization of authorizations.value) {
    if (authorization.skill_id !== result.skill_id) continue
    authorization.global_state = result.global_state
    if (authorization.agent_id === result.agent_id) {
      applyResult(authorization, result)
    } else if (authorization.agent_state === 'default') {
      authorization.effective = inheritedEffective(authorization)
    }
  }
}

function applyCategoryResult(result: SkillCategoryAuthorizationResult): void {
  for (const authorization of authorizations.value) {
    if (
      authorization.category_id !== result.category_id
      || authorization.agent_id !== result.agent_id
    ) continue
    authorization.category_state = result.state
    if (authorization.agent_state === 'default') {
      authorization.effective = inheritedEffective(authorization)
    }
  }
}

async function onGlobalState(
  row: SkillAuthorization,
  state: SkillGlobalAuthorizationState,
): Promise<void> {
  try {
    const result = (
      await skillService.setGlobalAuthorization(row.skill_id, row.agent_id, state)
    ).data
    applyGlobalResult(result)
    $q.notify({ type: 'positive', message: t('skills.auth.updated') })
  } catch (error) {
    console.error('Error updating global skill authorization:', error)
    $q.notify({ type: 'negative', message: t('skills.auth.updateError') })
    void loadAuthorizations()
  }
}

async function onAgentState(
  row: SkillAuthorization,
  state: SkillAuthorizationState,
): Promise<void> {
  try {
    const result = (
      await skillService.setAgentAuthorization(row.skill_id, row.agent_id, state)
    ).data
    applyResult(row, result)
    $q.notify({ type: 'positive', message: t('skills.auth.updated') })
  } catch (error) {
    console.error('Error updating agent skill authorization:', error)
    $q.notify({ type: 'negative', message: t('skills.auth.updateError') })
    void loadAuthorizations()
  }
}

async function onCategoryState(
  row: SkillAuthorization,
  state: SkillCategoryAuthorizationState,
): Promise<void> {
  if (row.category_id === null) return
  try {
    const result = (
      await skillService.setCategoryAuthorization(row.category_id, row.agent_id, state)
    ).data
    applyCategoryResult(result)
    $q.notify({ type: 'positive', message: t('skills.auth.updated') })
  } catch (error) {
    console.error('Error updating skill category authorization:', error)
    $q.notify({ type: 'negative', message: t('skills.auth.updateError') })
    void loadAuthorizations()
  }
}

function loadSession(): void {
  const agent = Number(sessionStorage.getItem(SESSION_AGENT_KEY))
  if (Number.isFinite(agent) && agent > 0) filterAgentId.value = agent
  const skill = Number(sessionStorage.getItem(SESSION_SKILL_KEY))
  if (Number.isFinite(skill) && skill > 0) filterSkillId.value = skill
  const category = Number(sessionStorage.getItem(SESSION_CATEGORY_KEY))
  if (Number.isFinite(category) && category > 0) filterCategoryId.value = category
}

function saveOptionalFilter(key: string, value: number | null): void {
  if (value === null) sessionStorage.removeItem(key)
  else sessionStorage.setItem(key, String(value))
}

watch(
  [filterAgentId, filterSkillId, filterCategoryId],
  ([agentId, skillId, categoryId]) => {
    saveOptionalFilter(SESSION_AGENT_KEY, agentId)
    saveOptionalFilter(SESSION_SKILL_KEY, skillId)
    saveOptionalFilter(SESSION_CATEGORY_KEY, categoryId)
    if (ready.value) void loadAuthorizations()
  },
  { flush: 'sync' },
)

watch(
  () => ({
    skills: store.skills.map(skill => `${skill.id}:${skill.category_id ?? 'none'}`),
    categories: store.categories.map(category => `${category.id}:${category.label}`),
  }),
  () => {
    if (!ready.value) return
    if (
      filterSkillId.value !== null
      && !skillOptions.value.some(option => option.value === filterSkillId.value)
    ) {
      filterSkillId.value = null
      return
    }
    if (
      filterCategoryId.value !== null
      && !categoryOptions.value.some(option => option.value === filterCategoryId.value)
    ) {
      filterCategoryId.value = null
      return
    }
    void loadAuthorizations()
  },
)

onMounted(async () => {
  try {
    await Promise.all([
      store.fetchAgents(),
      store.fetchSkills(),
      store.fetchCategories(),
      agentStore.agents.length ? Promise.resolve() : agentStore.fetchAgents(),
    ])
    loadSession()
    if (!agentOptions.value.some(option => option.value === filterAgentId.value)) {
      filterAgentId.value = null
    }
    if (!skillOptions.value.some(option => option.value === filterSkillId.value)) {
      filterSkillId.value = null
    }
    if (!categoryOptions.value.some(option => option.value === filterCategoryId.value)) {
      filterCategoryId.value = null
    }
  } catch (error) {
    console.error('Error loading skill authorization filters:', error)
    loadError.value = t('skills.auth.loadError')
  } finally {
    ready.value = true
    await loadAuthorizations()
  }
})
</script>

<style scoped>
.section-label {
  display: inline-flex;
  align-items: center;
}

.authorization-category-heading {
  min-height: 32px;
}

.agent-identity-text {
  min-width: 0;
}

:deep(.authorization-table .q-table__grid-content) {
  width: 100%;
  margin: 0;
}

:deep(.authorization-table .q-table__grid-item) {
  min-width: 0;
  max-width: 100%;
}

.authorization-grid-item {
  padding: 8px 0;
}

.authorization-mobile-card,
.authorization-mobile-copy {
  min-width: 0;
}

.authorization-mobile-code,
.authorization-mobile-description {
  overflow-wrap: anywhere;
}

.authorization-mobile-label {
  color: #757575;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.authorization-mobile-controls {
  display: grid;
  gap: 16px;
}

:deep(.q-table) {
  table-layout: fixed;
  width: 100%;
  min-width: 1000px;
}

:deep(.q-table th),
:deep(.q-table td) {
  padding: 12px;
  white-space: normal;
  word-break: break-word;
  vertical-align: top;
}

:deep(.q-table .q-btn-toggle) {
  flex-wrap: wrap;
}

:deep(.q-table .q-btn-toggle .q-btn) {
  flex: 1 1 auto;
}

@media (max-width: 1023px) {
  .authorization-category-heading {
    min-width: 0;
  }

  .authorization-category-heading .text-h6 {
    min-width: 0;
    overflow-wrap: anywhere;
  }
}
</style>
