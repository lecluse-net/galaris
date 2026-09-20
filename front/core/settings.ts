export class Settings {
    readonly APP_LABEL = 'Galaris'
    readonly APP_ENV: string
    readonly APP_NAME: string
    readonly APP_VERSION: string

    constructor(env: { VITE_APP_ENV?: string; VITE_APP_NAME?: string; VITE_BUILD_VERSION?: string } = {}) {
        this.APP_ENV = env.VITE_APP_ENV ?? 'prod'
        this.APP_NAME = env.VITE_APP_NAME || 'galaris'
        this.APP_VERSION = env.VITE_BUILD_VERSION === 'unknown' ? '' : (env.VITE_BUILD_VERSION ?? '')
    }

    get is_dev(): boolean {
        return this.APP_ENV === 'dev'
    }

}

// Singleton created when the module loads.
// Usage: import { settings } from './settings'
export const settings = new Settings(import.meta.env)
