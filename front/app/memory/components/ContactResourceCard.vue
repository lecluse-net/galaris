<template>
  <section ref="card" class="contact-resource-card" :aria-label="t('contacts.coordinates')">
    <q-icon name="contact_page" color="primary" size="40px" aria-hidden="true" />
    <div v-if="loading" role="status"><q-spinner color="primary" /></div>
    <div v-else-if="error" role="alert">
      {{ t('contacts.loadError') }}
      <q-btn flat round dense color="primary" icon="refresh" :aria-label="t('common.retry')" @click.stop.prevent="refresh" />
    </div>
    <div v-else-if="contact" class="contact-resource-details">
      <div v-for="identity in contact.identities" :key="identity.id">{{ identity.namespace || t('contacts.identityGalaris') }} · {{ identity.external_id }}</div>
      <div v-for="(phone, index) in contact.coordinates.phone_numbers" :key="`phone-${index}`">{{ [phone.label, phone.number].filter(Boolean).join(' · ') }}</div>
      <div v-for="(address, index) in contact.coordinates.postal_addresses" :key="`address-${index}`">{{ [address.label, address.street, address.postal_code, address.city, address.region, address.country].filter(Boolean).join(', ') }}</div>
    </div>
  </section>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useTemplateRef } from 'vue'
import { captureElementRendering } from '@/core/util'
import { contactService } from '../services/contactService'
import { useContactResource } from '../useContactResource'
const { contactId } = defineProps<{ contactId: string }>()
const { t } = useI18n()
const { contact, loading, error, refresh } = useContactResource(() => contactId)
const card = useTemplateRef<HTMLElement>('card')
async function capture(signal: AbortSignal): Promise<string> {
  // An export must recheck access rather than reuse sensitive rendered data
  // after a permission change that happened outside this browser session.
  const current = contact.value
  if (!card.value || loading.value || error.value || !current) throw new Error('Contact rendering unavailable')
  await contactService.get(contactId, signal)
  if (contact.value !== current) throw new Error('Contact context changed')
  const html = await captureElementRendering(card.value, signal)
  if (contact.value !== current) throw new Error('Contact context changed')
  return html
}
defineExpose({ capture })
</script>
<style scoped>
.contact-resource-card { display: flex; gap: 16px; align-items: flex-start; padding: 12px; border-radius: 8px; background: var(--solaire-blue-light); }
.contact-resource-details { min-width: 0; overflow-wrap: anywhere; font-size: 13px; line-height: 1.6; }
:global(body.body--dark .contact-resource-card) { background: var(--solaire-blue-dark); }
</style>
