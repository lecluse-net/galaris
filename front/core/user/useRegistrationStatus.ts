import { onScopeDispose, ref } from 'vue'
import { authService } from './services/authService'

export function useRegistrationStatus() {
    const registrationOpen = ref(false)
    const checkingRegistration = ref(false)
    const registrationStatusError = ref(false)
    let active = true
    let generation = 0
    onScopeDispose(() => { active = false })

    async function checkRegistration(): Promise<boolean | undefined> {
        const request = ++generation
        checkingRegistration.value = true
        registrationStatusError.value = false
        registrationOpen.value = false
        try {
            const status = await authService.getRegistrationStatus()
            if (!active || request !== generation) return
            registrationOpen.value = status.registration_open
            return status.registration_open
        } catch {
            if (active && request === generation) registrationStatusError.value = true
        } finally {
            if (active && request === generation) checkingRegistration.value = false
        }
    }

    return { registrationOpen, checkingRegistration, registrationStatusError, checkRegistration }
}
