import type { SettingField } from '@/core/params'

export const browserFields: SettingField[] = [
    { name: 'BROWSER_SESSION_TTL_SECONDS', labelKey: 'browserSettings.fields.sessionTtl', input: 'integer', min: 10, max: 3600 },
    { name: 'BROWSER_MAX_SESSIONS', labelKey: 'browserSettings.fields.maxSessions', input: 'integer', min: 1, max: 256 },
    { name: 'BROWSER_EXECUTOR_TIMEOUT_SECONDS', labelKey: 'browserSettings.fields.timeout', input: 'number', min: 5, max: 180 },
    { name: 'BROWSER_VIEWPORT_WIDTH', labelKey: 'browserSettings.fields.viewportWidth', input: 'integer', min: 320, max: 3840 },
    { name: 'BROWSER_VIEWPORT_HEIGHT', labelKey: 'browserSettings.fields.viewportHeight', input: 'integer', min: 240, max: 2160 },
    { name: 'BROWSER_CONTENT_MAX_CHARS', labelKey: 'browserSettings.fields.contentMaxChars', input: 'integer', min: 1000, max: 200000 },
    { name: 'BROWSER_HTML_MAX_BYTES', labelKey: 'browserSettings.fields.htmlMaxBytes', input: 'integer', sizeUnit: 'bytes', min: 10000, max: 750000 },
    { name: 'BROWSER_SCREENSHOT_TILE_HEIGHT', labelKey: 'browserSettings.fields.tileHeight', input: 'integer', min: 500, max: 10000 },
    { name: 'BROWSER_SCREENSHOT_MAX_TILES', labelKey: 'browserSettings.fields.maxTiles', input: 'integer', min: 1, max: 30 },
    { name: 'BROWSER_SCREENSHOT_MAX_TOTAL_BYTES', labelKey: 'browserSettings.fields.maxTotalBytes', input: 'integer', sizeUnit: 'bytes', min: 1000000, max: 100000000 },
]
