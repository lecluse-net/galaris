import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { tokenService, type UserToken, type UserTokenUpdate } from '../services/tokenService'
import { i18n } from '@/core/i18n'

export type { UserToken }

export const useTokenStore = defineStore('token', () => {
    // State
    const tokens = ref<UserToken[]>([])
    const loading = ref(false)
    const error = ref<string | null>(null)

    // Getters
    const enabledTokens = computed(() => tokens.value.filter(t => t.enabled))
    const disabledTokens = computed(() => tokens.value.filter(t => !t.enabled))

    // Actions
    async function fetchTokens(): Promise<void> {
        loading.value = true
        error.value = null
        try {
            const data = await tokenService.listTokens()
            tokens.value = data
        } catch (err) {
            console.error('Error fetching tokens:', err)
            error.value = i18n.global.t('tokens.loadError')
            throw err
        } finally {
            loading.value = false
        }
    }

    async function createToken(label?: string): Promise<UserToken> {
        loading.value = true
        error.value = null
        try {
            const token = await tokenService.createToken(label ? { label } : {})
            tokens.value.unshift(token)
            return token
        } catch (err) {
            console.error('Error creating token:', err)
            error.value = i18n.global.t('tokens.createError')
            throw err
        } finally {
            loading.value = false
        }
    }

    async function toggleToken(tokenId: number): Promise<UserToken> {
        loading.value = true
        error.value = null
        try {
            const existing = tokens.value.find(t => t.id === tokenId)
            const updateData: UserTokenUpdate = {
                enabled: !existing?.enabled
            }
            const token = await tokenService.updateToken(tokenId, updateData)
            const index = tokens.value.findIndex(t => t.id === tokenId)
            if (index !== -1) {
                tokens.value[index] = token
            }
            return token
        } catch (err) {
            console.error('Error updating token:', err)
            error.value = i18n.global.t('tokens.toggleError')
            throw err
        } finally {
            loading.value = false
        }
    }

    async function updateTokenLabel(tokenId: number, label: string): Promise<UserToken> {
        loading.value = true
        error.value = null
        try {
            const updateData: UserTokenUpdate = { label }
            const token = await tokenService.updateToken(tokenId, updateData)
            const index = tokens.value.findIndex(t => t.id === tokenId)
            if (index !== -1) {
                tokens.value[index] = token
            }
            return token
        } catch (err) {
            console.error('Error updating token label:', err)
            error.value = i18n.global.t('tokens.labelUpdateError')
            throw err
        } finally {
            loading.value = false
        }
    }

    async function deleteToken(tokenId: number): Promise<void> {
        loading.value = true
        error.value = null
        try {
            await tokenService.deleteToken(tokenId)
            tokens.value = tokens.value.filter(t => t.id !== tokenId)
        } catch (err) {
            console.error('Error deleting token:', err)
            error.value = i18n.global.t('tokens.deleteError')
            throw err
        } finally {
            loading.value = false
        }
    }

    return {
        tokens,
        loading,
        error,
        enabledTokens,
        disabledTokens,
        fetchTokens,
        createToken,
        toggleToken,
        updateTokenLabel,
        deleteToken
    }
})
