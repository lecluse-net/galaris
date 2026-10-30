<template>
  <section class="q-mb-lg" :aria-label="t('contacts.coordinates')">
    <div class="text-subtitle2 q-mb-md">{{ t('contacts.coordinates') }}</div>
    <q-banner v-if="defaultsError" class="q-mb-md" role="alert">
      {{ t('contacts.countryDefaultError') }}
      <template #action>
        <q-btn flat round color="primary" icon="refresh" :aria-label="t('contacts.retryCountry')" @click="loadDefaults" />
      </template>
    </q-banner>
    <q-card v-for="(phone, index) in model.phone_numbers" :key="index" flat bordered role="group"
      :aria-label="t('contacts.phoneNumbered', { number: index + 1 })" class="coordinate-entry q-pa-md q-mb-md">
      <div class="row items-center justify-between q-mb-sm">
        <span class="text-subtitle2">{{ t('contacts.phoneNumbered', { number: index + 1 }) }}</span>
        <q-btn flat round color="negative" icon="delete_outline" :disable="disabled"
          :aria-label="t('contacts.removePhone', { number: index + 1 })" @click="model.phone_numbers.splice(index, 1)" />
      </div>
      <q-input v-model="phone.number" outlined type="tel" maxlength="80" :disable="disabled"
        :label="t('contacts.phone')" :rules="[(value: string) => value.trim().length >= 3 || t('contacts.phoneRequired')]" />
      <div class="row q-col-gutter-md">
        <q-input v-model="phone.label" outlined maxlength="80" class="col-12 col-sm-6" :disable="disabled" :label="t('contacts.coordinateLabel')" />
        <q-input v-model="phone.country" outlined maxlength="100" class="col-12 col-sm-6" :disable="disabled"
          :label="t('contacts.country')" :hint="t('contacts.countryHint')" />
      </div>
    </q-card>
    <q-card v-for="(address, index) in model.postal_addresses" :key="index" flat bordered role="group"
      :aria-label="t('contacts.addressNumbered', { number: index + 1 })" class="coordinate-entry q-pa-md q-mb-md">
      <div class="row items-center justify-between q-mb-sm">
        <span class="text-subtitle2">{{ t('contacts.addressNumbered', { number: index + 1 }) }}</span>
        <q-btn flat round color="negative" icon="delete_outline" :disable="disabled"
          :aria-label="t('contacts.removeAddress', { number: index + 1 })" @click="model.postal_addresses.splice(index, 1)" />
      </div>
      <q-input v-model="address.street" outlined type="textarea" rows="2" maxlength="1000" :disable="disabled"
        :label="t('contacts.street')" :rules="[() => hasAddress(address) || t('contacts.addressRequired')]" />
      <div class="row q-col-gutter-md">
        <q-input v-model="address.postal_code" outlined maxlength="50" class="col-12 col-sm-6 q-mb-md" :disable="disabled" :label="t('contacts.postalCode')" />
        <q-input v-model="address.city" outlined maxlength="200" class="col-12 col-sm-6 q-mb-md" :disable="disabled" :label="t('contacts.city')" />
        <q-input v-model="address.region" outlined maxlength="200" class="col-12 col-sm-6 q-mb-md" :disable="disabled" :label="t('contacts.region')" />
        <q-input v-model="address.country" outlined maxlength="100" class="col-12 col-sm-6 q-mb-md" :disable="disabled"
          :label="t('contacts.country')" :hint="t('contacts.countryHint')" />
      </div>
      <q-input v-model="address.label" outlined maxlength="80" :disable="disabled" :label="t('contacts.coordinateLabel')" />
    </q-card>
    <div class="row q-gutter-sm">
      <q-btn outline color="primary" icon="add_call" :label="t('contacts.addPhone')"
        :disable="disabled || loadingDefaults || model.phone_numbers.length >= 50" @click="addPhone" />
      <q-btn outline color="primary" icon="add_location_alt" :label="t('contacts.addAddress')"
        :disable="disabled || loadingDefaults || model.postal_addresses.length >= 50" @click="addAddress" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { contactService } from '../services/contactService'
import type { ContactCoordinates, ContactPostalAddress } from '../types'

const model = defineModel<ContactCoordinates>({ required: true })
const { disabled = false } = defineProps<{ disabled?: boolean }>()
const { t } = useI18n()
const country = ref('')
const loadingDefaults = ref(true)
const defaultsError = ref(false)
let active = true
onBeforeUnmount(() => { active = false })
onMounted(loadDefaults)

async function loadDefaults(): Promise<void> {
  loadingDefaults.value = true
  defaultsError.value = false
  try {
    const result = await contactService.defaults()
    if (active) country.value = result.country
  } catch {
    if (active) defaultsError.value = true
  } finally {
    if (active) loadingDefaults.value = false
  }
}

function addPhone(): void {
  model.value.phone_numbers.push({ label: '', number: '', country: country.value })
}

function addAddress(): void {
  model.value.postal_addresses.push({ label: '', street: '', postal_code: '', city: '', region: '', country: country.value })
}

function hasAddress(address: ContactPostalAddress): boolean {
  return [address.street, address.postal_code, address.city, address.region].some(value => value.trim())
}
</script>
