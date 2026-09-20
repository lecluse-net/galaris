import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('./settings.ts', import.meta.url), 'utf8')
const output = ts.transpileModule(source.replace('import.meta.env', '{}'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const loaded = { exports: {} }
new Function('module', 'exports', output)(loaded, loaded.exports)
const { Settings } = loaded.exports

for (const environment of ['dev', 'prod', 'pp', 'test', 'demo', 'custom', 'DEV', '']) {
    test(`environment ${JSON.stringify(environment)} preserves its label and only dev enables development`, () => {
        const settings = new Settings({ VITE_APP_ENV: environment })
        assert.equal(settings.APP_ENV, environment)
        assert.equal(settings.is_dev, environment === 'dev')
    })
}

test('an absent environment defaults to prod', () => {
    const settings = new Settings()
    assert.equal(settings.APP_ENV, 'prod')
    assert.equal(settings.is_dev, false)
})
