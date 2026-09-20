import axios, { type AxiosInstance, type InternalAxiosRequestConfig, type AxiosError } from 'axios'
import { i18n } from './i18n'

// Use the Nginx API proxy. Requests go through /api in development and production.
const API_URL = '/api'
const ACCESS_TOKEN_KEY = 'access_token'
const USER_KEY = 'user'
const SESSION_GENERATION_KEY = 'galaris:session-generation'
const REQUEST_TIMEOUT_MS = 60_000

export const AUTH_TOKEN_CHANGED_EVENT = 'galaris:auth-token-changed'

interface TokenResponse {
    access_token: string
    token_type: string
}

interface RetryableRequestConfig extends InternalAxiosRequestConfig {
    _retriedAfterRefresh?: boolean
    _sessionGeneration?: string
}

let refreshInFlight: Promise<string> | null = null
let authQueue: Promise<unknown> = Promise.resolve()
const beforeLogoutHooks = new Set<() => Promise<void>>()
const originalErrorMessages = new WeakMap<Error, string>()

export class SupersededSessionError extends Error {
    constructor() { super('Session changed while the request was running') }
}

export function isCancelledRequest(error: unknown): boolean {
    return error instanceof SupersededSessionError
        || (axios.isAxiosError(error) && error.code === 'ERR_CANCELED')
}

export function sessionGeneration(): string {
    return localStorage.getItem(SESSION_GENERATION_KEY) ?? ''
}

export function invalidateSessionRequests(): void {
    localStorage.setItem(SESSION_GENERATION_KEY, crypto.randomUUID())
    refreshInFlight = null
}

/** Cookie-changing requests must finish in order, including across browser tabs. */
export function withSessionLock<T>(operation: () => Promise<T>): Promise<T> {
    const run = () => typeof navigator !== 'undefined' && navigator.locks
        ? navigator.locks.request('galaris:session-cookie', operation)
        : operation()
    const result = authQueue.then(run, run)
    authQueue = result.catch(() => undefined)
    return result
}

export function registerBeforeLogoutHook(hook: () => Promise<void>): () => void {
    beforeLogoutHooks.add(hook)
    return () => beforeLogoutHooks.delete(hook)
}

export async function runBeforeLogoutHooks(): Promise<void> {
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
        await Promise.race([
            Promise.allSettled([...beforeLogoutHooks].map(hook => Promise.resolve().then(hook))),
            new Promise<void>(resolve => { timer = setTimeout(resolve, 1_000) })
        ])
    } finally {
        clearTimeout(timer)
    }
}

export function getStoredAccessToken(): string | null {
    return localStorage.getItem(ACCESS_TOKEN_KEY)
}

export function saveAccessToken(token: string): void {
    invalidateSessionRequests()
    persistAccessToken(token)
}

function persistAccessToken(token: string): void {
    localStorage.setItem(ACCESS_TOKEN_KEY, token)
    window.dispatchEvent(new CustomEvent<string>(AUTH_TOKEN_CHANGED_EVENT, { detail: token }))
}

export function clearStoredSession(): void {
    invalidateSessionRequests()
    localStorage.removeItem(ACCESS_TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    window.dispatchEvent(new CustomEvent<null>(AUTH_TOKEN_CHANGED_EVENT, { detail: null }))
}

function validationDetail(value: unknown): string | null {
    if (!value || typeof value !== 'object') return null
    const entry = value as { loc?: unknown, message?: unknown, msg?: unknown }
    const message = typeof entry.message === 'string'
        ? entry.message
        : typeof entry.msg === 'string' ? entry.msg : null
    if (!message) return null
    const location = Array.isArray(entry.loc)
        ? entry.loc.filter(part => typeof part === 'string' || typeof part === 'number').join('.')
        : ''
    return location ? `${location}: ${message}` : message
}

/** Return a bounded, user-safe detail supplied by the API or HTTP client. */
export function apiErrorDetail(error: unknown): string | null {
    if (!axios.isAxiosError(error)) {
        return error instanceof Error && error.message.trim()
            ? error.message.trim().slice(0, 2_000)
            : null
    }
    if (error.code === 'ERR_CANCELED') return error.message
    const originalMessage = originalErrorMessages.get(error) ?? error.message ?? ''
    const data = error.response?.data as { detail?: unknown } | undefined
    const detail = data?.detail
    let message = typeof detail === 'string' ? detail.trim().slice(0, 2_000) : ''
    if (!message && Array.isArray(detail)) {
        const messages = detail.map(validationDetail).filter((value): value is string => value !== null)
        if (messages.length) message = messages.join('\n').slice(0, 2_000)
    }
    const status = error.response?.status
    const timedOut = error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT'
    const cause = error.cause instanceof Error ? error.cause.message.trim().slice(0, 500) : ''
    if (!message) {
        if (cause) message = cause
        else if (status) message = i18n.global.t('common.apiError.http')
        else if (timedOut) message = i18n.global.t('common.apiError.timeout')
        else if (error.code === 'ERR_NETWORK' || error.request) message = i18n.global.t('common.apiError.network')
        else return originalMessage.trim().slice(0, 2_000) || null
    }

    const diagnostic: string[] = []
    const config = error.config
    if (config?.url) {
        // Show the route, never URL credentials, query parameters or fragments.
        const combined = /^(?:https?:)?\/\//i.test(config.url)
            ? config.url
            : `${config.baseURL?.replace(/\/$/, '') ?? ''}/${config.url.replace(/^\//, '')}`
        try {
            const path = new URL(combined, 'https://galaris.invalid').pathname
            diagnostic.push(`${(config.method ?? 'get').toUpperCase()} ${path.slice(0, 500)}`)
        } catch { /* A malformed URL must not obscure the original error. */ }
    }
    if (status) diagnostic.push(`HTTP ${status}${error.response?.statusText ? ` ${error.response.statusText}` : ''}`)
    if (error.code) diagnostic.push(error.code)
    if (timedOut && config?.timeout) {
        diagnostic.push(i18n.global.t('common.apiError.timeoutLimit', { seconds: config.timeout / 1_000 }))
    }
    if (!status && typeof navigator !== 'undefined' && navigator.onLine === false) {
        diagnostic.push(i18n.global.t('common.apiError.offline'))
    }
    if (originalMessage.trim()) diagnostic.push(originalMessage.trim().slice(0, 500))
    if (cause && cause !== message && cause !== originalMessage) {
        diagnostic.push(cause)
    }
    return diagnostic.length
        ? i18n.global.t('common.apiError.diagnostic', { message, diagnostic: diagnostic.join(' · ') })
        : message
}

/** Preserve the Axios error and its metadata for all consumers, including raw error.message displays. */
function explainApiError(error: unknown): void {
    if (!axios.isAxiosError(error)) return
    if (!originalErrorMessages.has(error)) originalErrorMessages.set(error, error.message ?? '')
    const detail = apiErrorDetail(error)
    if (detail) error.message = detail
}

function isAuthenticationRequest(url?: string): boolean {
    if (!url) return false
    return [
        '/auth/login',
        '/auth/login-json',
        '/auth/register',
        '/auth/refresh',
        '/auth/logout'
    ].some(path => url.includes(path))
}

export function refreshAccessToken(): Promise<string> {
    if (refreshInFlight) return refreshInFlight

    const previousToken = getStoredAccessToken()
    const generation = sessionGeneration()
    const request = withSessionLock(async () => {
        if (generation !== sessionGeneration()) throw new SupersededSessionError()
        // Another tab may have renewed the same session while we waited.
        const currentToken = getStoredAccessToken()
        if (currentToken && currentToken !== previousToken) return currentToken
        const response = await axios.post<TokenResponse>(
        `${API_URL}/auth/refresh`,
        undefined,
        {
            withCredentials: true,
            // A document navigation must not discard the in-flight cookie
            // rotation. The server's existing replay policy stays unchanged.
            adapter: 'fetch',
            fetchOptions: { keepalive: true },
            timeout: 15_000,
            headers: previousToken
                ? { Authorization: `Bearer ${previousToken}` }
                : undefined
        }
        )
        if (generation !== sessionGeneration()) throw new SupersededSessionError()
        persistAccessToken(response.data.access_token)
        return response.data.access_token
    }).catch((error: unknown) => {
        explainApiError(error)
        throw error
    }).finally(() => {
        if (refreshInFlight === request) refreshInFlight = null
    })
    refreshInFlight = request
    return request
}

function redirectToGuestHome(): void {
    if (window.location.pathname !== '/') {
        window.location.href = '/'
    }
}

const api: AxiosInstance = axios.create({
    baseURL: API_URL,
    withCredentials: true,
    timeout: REQUEST_TIMEOUT_MS,
    headers: {
        'Content-Type': 'application/json'
    }
})

// Add the JWT to authenticated requests.
api.interceptors.request.use((config: RetryableRequestConfig) => {
    if (config._sessionGeneration !== undefined && config._sessionGeneration !== sessionGeneration()) {
        throw new SupersededSessionError()
    }
    config._sessionGeneration = sessionGeneration()
    // Let the browser generate the multipart boundary. Keeping the instance-wide
    // application/json header would serialize FormData and drop uploaded files.
    if (config.data instanceof FormData) {
        config.headers.delete('Content-Type')
        if (config.timeout === REQUEST_TIMEOUT_MS) config.timeout = 600_000
    }
    if (config.responseType === 'blob' && config.timeout === REQUEST_TIMEOUT_MS) {
        config.timeout = 600_000
    }
    const token = getStoredAccessToken()
    if (token) {
        config.headers.Authorization = `Bearer ${token}`
    }
    return config
})

// Handle expired sessions.
api.interceptors.response.use(
    (response) => {
        const config = response.config as RetryableRequestConfig
        if (!isAuthenticationRequest(config.url) && config._sessionGeneration !== sessionGeneration()) {
            throw new SupersededSessionError()
        }
        return response
    },
    async (error: AxiosError) => {
        const config = error.config as RetryableRequestConfig | undefined
        if (config?._sessionGeneration !== undefined && config._sessionGeneration !== sessionGeneration()) {
            return Promise.reject(new SupersededSessionError())
        }
        if (
            error.response?.status === 401
            && config
            && !config._retriedAfterRefresh
            && !isAuthenticationRequest(config.url)
        ) {
            config._retriedAfterRefresh = true
            const generation = sessionGeneration()
            try {
                const token = await refreshAccessToken()
                if (generation !== sessionGeneration()) throw new SupersededSessionError()
                config.headers.Authorization = `Bearer ${token}`
            } catch (refreshError) {
                if (generation === sessionGeneration() && axios.isAxiosError(refreshError) && refreshError.response?.status === 401) {
                    clearStoredSession()
                    redirectToGuestHome()
                }
                return Promise.reject(refreshError)
            }
            return api.request(config)
        }
        explainApiError(error)
        return Promise.reject(error)
    }
)

export default api
export { api }
