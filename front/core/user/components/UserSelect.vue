<template>
  <q-select v-model="model" :options="options" :label="label" :stack-label="Boolean(label)" emit-value map-options v-bind="$attrs"
    :aria-label="typeof $attrs['aria-label'] === 'string' ? $attrs['aria-label'] : label">
    <template v-if="$slots.prepend" #prepend><slot name="prepend" /></template>
    <template #selected>
      <div v-if="selectedOption" class="row items-center no-wrap q-gutter-sm">
        <UserAvatar v-if="selectedOption.value !== null" :name="selectedOption.label"
          :avatar-url="selectedOption.avatarUrl" size="28px" />
        <span class="ellipsis">{{ selectedOption.label }}</span>
      </div>
      <span v-else class="text-grey-7">{{ t('user.selectPlaceholder') }}</span>
    </template>
    <template #option="scope">
      <q-item v-bind="scope.itemProps" :aria-label="scope.opt.label">
        <q-item-section v-if="scope.opt.value !== null" avatar>
          <UserAvatar :name="scope.opt.label" :avatar-url="scope.opt.avatarUrl" size="32px" />
        </q-item-section>
        <q-item-section>
          <q-item-label>{{ scope.opt.label }}</q-item-label>
          <q-item-label v-if="scope.opt.caption" caption>{{ scope.opt.caption }}</q-item-label>
        </q-item-section>
      </q-item>
    </template>
  </q-select>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import UserAvatar from './UserAvatar.vue'

defineOptions({ inheritAttrs: false })
interface UserSelectOption {
  label: string
  value: number | null
  avatarUrl?: string | null
  caption?: string
  disable?: boolean
}
const { options, label } = defineProps<{ options: readonly UserSelectOption[]; label?: string }>()
const model = defineModel<number | null>({ required: true })
const { t } = useI18n()
const selectedOption = computed(() => options.find(option => option.value === model.value) ?? null)
</script>
