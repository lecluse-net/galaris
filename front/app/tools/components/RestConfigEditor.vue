<template>
  <div class="q-gutter-y-md">
    <p class="text-body2">{{ t('tools.restHelp') }}</p>
    <q-input v-model="config.base_url" outlined dense :label="t('tools.restBaseUrl')" :hint="t('tools.restBaseUrlHint')" />
    <q-select v-model="config.auth.type" :options="authOptions" emit-value map-options outlined dense :label="t('tools.restAuth')" />
    <ConnectionParamSelect v-if="['bearer', 'header', 'query'].includes(config.auth.type)" v-model="config.auth.param"
      :options="secretParams" :create-parameter="() => createParam('api_token', 'password', t('tools.restTokenParam'))"
      outlined dense :label="t('tools.restTokenParam')" />
    <q-input v-if="config.auth.type === 'header'" v-model="config.auth.header_name" outlined dense :label="t('tools.headerName')" />
    <q-input v-if="config.auth.type === 'query'" v-model="config.auth.query_name" outlined dense :label="t('tools.restQueryName')" />
    <template v-if="config.auth.type === 'basic'">
      <ConnectionParamSelect v-model="config.auth.login_param" :options="paramNames"
        :create-parameter="() => createParam('login', 'string', t('tools.loginParam'))" outlined dense :label="t('tools.loginParam')" />
      <ConnectionParamSelect v-model="config.auth.password_param" :options="secretParams"
        :create-parameter="() => createParam('password', 'password', t('tools.passwordParam'))" outlined dense :label="t('tools.passwordParam')" />
    </template>
    <div class="row q-col-gutter-md">
      <q-input v-model.number="config.timeout" type="number" min="1" max="300" outlined dense class="col-12 col-md-6" :label="t('tools.restTimeout')" />
      <q-input v-model.number="config.max_response_bytes" type="number" min="1" max="16777216" outlined dense class="col-12 col-md-6" :label="t('tools.restMaxResponse')" />
    </div>
    <div>
      <div class="text-subtitle2">{{ t('tools.restHeaders') }}</div>
      <div v-for="(row, index) in headerRows" :key="index" class="row q-col-gutter-sm q-mt-xs items-center">
        <q-input v-model="row.name" outlined dense class="col" :label="t('tools.headerName')" @update:model-value="saveHeaders" />
        <ConnectionParamSelect v-model="row.param" :options="paramNames"
          :create-parameter="() => createParam(row.name || 'header', 'string', row.name || t('tools.valueParam'))"
          outlined dense class="col" :label="t('tools.valueParam')" @update:model-value="saveHeaders" />
        <q-btn flat round icon="delete" :aria-label="t('common.delete')" @click="headerRows.splice(index, 1); saveHeaders()" />
      </div>
      <q-btn outline icon="add" :label="t('tools.restAddHeader')" @click="headerRows.push({ name: '', param: '' })" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ConnectionParamDef, RestConfig } from '../services/toolService'
import ConnectionParamSelect from './ConnectionParamSelect.vue'

const config = defineModel<RestConfig>({ required: true })
const props = defineProps<{
  params: Array<ConnectionParamDef & { name: string }>
  createParam: (baseName: string, type: string, label: string) => string
}>()
const { t } = useI18n()
const paramNames = computed(() => props.params.map(param => param.name).filter(Boolean))
const secretParams = computed(() => props.params.filter(param => param.type === 'password').map(param => param.name).filter(Boolean))
const authOptions = computed(() => [
  { value: 'none', label: t('tools.restAuthNone') },
  { value: 'bearer', label: t('tools.restAuthBearer') },
  { value: 'header', label: t('tools.restAuthHeader') },
  { value: 'basic', label: t('tools.restAuthBasic') },
  { value: 'query', label: t('tools.restAuthQuery') },
])
const headerRows = ref<Array<{ name: string; param: string }>>([])
watch(() => config.value, value => {
  headerRows.value = Object.entries(value.header_params).map(([name, param]) => ({ name, param }))
}, { immediate: true })
function saveHeaders() {
  config.value.header_params = Object.fromEntries(headerRows.value.filter(row => row.name.trim() && row.param).map(row => [row.name.trim(), row.param]))
}
</script>
