<template>
      <div class="row justify-end q-mb-md">
      <q-btn v-if="canEditGlobalCatalog" color="primary" icon="add" :label="$t('agent.newTitle')" @click="openTitleDialog()" />
    </div>

    <q-table
      :rows="agentStore.titles"
      :columns="titleColumns"
      row-key="id"
      :loading="agentStore.loading"
      :rows-per-page-options="[10, 20, 50, 100, 500]"
      :pagination="{ rowsPerPage: 50 }"
    >
      <template v-slot:body-cell-gender="props">
        <q-td :props="props">
          <q-chip
            :color="props.row.gender === 'M' ? 'blue' : 'pink'"
            text-color="white"
            size="sm"
          >
            {{ props.row.gender === 'M' ? $t('agent.genderM') : $t('agent.genderF') }}
          </q-chip>
        </q-td>
      </template>

      <template v-slot:body-cell-actions="props">
        <q-td :props="props" class="text-center">
          <q-btn :aria-label="$t('common.edit')" v-if="canEditGlobalCatalog" flat round color="primary" icon="edit" size="sm" @click="openTitleDialog(props.row)">
            <q-tooltip>{{ $t('common.edit') }}</q-tooltip>
          </q-btn>
          <q-btn :aria-label="$t('common.delete')" v-if="canEditGlobalCatalog" flat round color="negative" icon="delete" size="sm" @click="confirmDeleteTitle(props.row)">
            <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
          </q-btn>
        </q-td>
      </template>

      <template v-slot:no-data>
        <div class="full-width row flex-center text-grey-8 q-gutter-sm q-pa-lg">
          <q-icon size="2em" name="badge_outlined" />
          <span>{{ $t('agent.noTitleRegistered') }}</span>
        </div>
      </template>
    </q-table>

    <q-dialog v-model="showTitleDialog">
      <q-card class="galaris-dialog-card" style="min-width: 400px">
        <DialogHeader :title="isTitleEdit ? $t('agent.editTitleDialog') : $t('agent.addTitleDialog')" :close-label="$t('common.close')" />
        <q-card-section class="q-pt-md galaris-dialog-body">
          <q-form class="q-gutter-md" @submit="onTitleSubmit">
            <q-input
              :model-value="titleLabel(titleForm.label, $t)"
              @update:model-value="titleForm.label = String($event ?? '')"
              :label="$t('agent.labelField')"
              filled
              autofocus
              :rules="[value => !!value || $t('agent.labelRule')]"
              :hint="$t('agent.labelHint')"
            />
            <q-select
              v-model="titleForm.gender"
              :options="genderOptions"
              :label="$t('agent.genderField')"
              filled
              emit-value
              map-options
              :rules="[value => !!value || $t('agent.genderRule')]"
            />
            <div class="galaris-dialog-actions row justify-end q-mt-md q-gutter-sm q-pa-md">
              <q-btn outline :label="$t('common.cancel')" color="grey"  v-close-popup />
              <q-btn
                v-if="canEditGlobalCatalog"
                :label="isTitleEdit ? $t('common.edit') : $t('common.create')"
                type="submit"
                color="primary"
                :loading="agentStore.loading"
              />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>

</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useQuasar, type QTableColumn } from 'quasar'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { DialogHeader, showConfirmationDialog } from '@/core/util'
import type { Title } from '../contracts'
import { useAgentStore } from '../stores/agentStore'
import { titleLabel } from '../titleLabels'

const agentStore = useAgentStore()
const privilegeStore = usePrivilegeStore()
const { t } = useI18n()
const $q = useQuasar()
const canEditGlobalCatalog = computed(() => privilegeStore.hasPrivilege(privileges.AGENT_EDIT)
  && privilegeStore.hasPrivilege(privileges.AGENT_MANAGE_ALL))
const showTitleDialog = ref(false)
const isTitleEdit = ref(false)
const titleForm = reactive<{ id: number | null; label: string; gender: 'M' | 'F' | null }>({
  id: null,
  label: '',
  gender: null
})

const genderOptions = computed(() => [
  { label: t('agent.genderM'), value: 'M' },
  { label: t('agent.genderF'), value: 'F' }
])

const titleColumns = computed<QTableColumn[]>(() => [
  { name: 'label', label: t('agent.colLabel'), field: (row: Title) => titleLabel(row.label, t), sortable: true, align: 'left' },
  { name: 'gender', label: t('agent.colGender'), field: 'gender', sortable: true, align: 'center' },
  { name: 'actions', label: t('common.actions'), field: 'actions', align: 'center', style: 'width: 100px' }
])

const resetTitleForm = () => {
  titleForm.id = null
  titleForm.label = ''
  titleForm.gender = null
}

const openTitleDialog = (title: Title | null = null) => {
  if (title) {
    isTitleEdit.value = true
    Object.assign(titleForm, title)
  } else {
    isTitleEdit.value = false
    resetTitleForm()
  }
  showTitleDialog.value = true
}

const onTitleSubmit = async () => {
  if (!canEditGlobalCatalog.value || titleForm.gender === null) return
  try {
    const data = {
      label: titleForm.label,
      gender: titleForm.gender
    }

    if (isTitleEdit.value && titleForm.id !== null) {
      await agentStore.updateTitle(titleForm.id, data)
      $q.notify({ type: 'positive', message: t('agent.notify.titleUpdated') })
    } else {
      await agentStore.createTitle(data)
      $q.notify({ type: 'positive', message: t('agent.notify.titleCreated') })
    }
    showTitleDialog.value = false
  } catch (error) {
    $q.notify({ type: 'negative', message: t('common.anError') })
  }
}

function confirmDeleteTitle(title: Title): void {
  if (!canEditGlobalCatalog.value) return
  showConfirmationDialog({
    title: t('common.deleteConfirmTitle'),
    message: t('agent.confirmDeleteTitle', { name: titleLabel(title.label, t) }),
    ok: { label: t('common.delete'), color: 'negative' },
    cancel: true,
  }).onOk(async () => {
    if (!canEditGlobalCatalog.value) return
    try {
      await agentStore.deleteTitle(title.id)
      $q.notify({ type: 'positive', message: t('agent.notify.titleDeleted') })
    } catch {
      $q.notify({ type: 'negative', message: t('agent.notify.cannotDeleteTitle') })
    }
  })
}
</script>
