<template>
    <div>
        <q-form class="q-mt-sm" @submit="send">
            <q-input
                v-model.trim="recipient"
                type="email"
                :label="t('platformSmtp.testRecipient')"
                :rules="[value => Boolean(value) || t('auth.emailRequired')]"
                :readonly="sending"
                outlined dense hide-bottom-space
                @update:model-value="outcome = null"
            >
                <template #append>
                    <q-btn
                        type="submit"
                        color="primary"
                        icon="send"
                        :label="t('platformSmtp.sendTest')"
                        :loading="sending"
                        unelevated dense no-caps
                        class="q-px-sm"
                        @click.prevent="submitFromButton"
                    />
                </template>
            </q-input>
        </q-form>
        <p v-if="outcome" class="text-caption q-mt-sm q-mb-none"
            :class="outcome.error ? 'text-negative' : 'text-positive'"
            :role="outcome.error ? 'alert' : 'status'">
            {{ outcome.message }}
        </p>
    </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { isAxiosError } from 'axios'
import { useI18n } from 'vue-i18n'
import { paramsService } from '../services/paramsService'

const { t } = useI18n()
const recipient = ref('')
const sending = ref(false)
const outcome = ref<{ error: boolean; message: string } | null>(null)

function submitFromButton(event: Event): void {
    if (event.currentTarget instanceof HTMLButtonElement) {
        event.currentTarget.form?.requestSubmit()
    }
}

async function send(): Promise<void> {
    if (sending.value) return
    sending.value = true
    outcome.value = null
    try {
        await paramsService.sendPlatformSmtpTest(recipient.value)
        outcome.value = { error: false, message: t('platformSmtp.testAccepted') }
    } catch (error) {
        const detail = isAxiosError<{ detail?: string }>(error) ? error.response?.data?.detail : undefined
        outcome.value = {
            error: true,
            message: typeof detail === 'string' ? detail : t('platformSmtp.testFailed'),
        }
    } finally {
        sending.value = false
    }
}
</script>
