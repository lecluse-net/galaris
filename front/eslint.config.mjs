import js from '@eslint/js'
import ts from 'typescript-eslint'
import vue from 'eslint-plugin-vue'

// A repository-wide correctness gate. Formatting and gradual Any removal remain
// separate from bugs such as duplicate branches, invalid templates or prop mutations.
export default [
  { ignores: ['node_modules/**', 'dist/**', 'dev-dist/**', 'public/**', '**/*.d.ts'] },
  {
    files: ['**/*.{ts,mjs,js,vue}'],
    ...js.configs.recommended,
    rules: {
      ...js.configs.recommended.rules,
      // TypeScript checks bindings; JS test harnesses deliberately supply globals.
      'no-undef': 'off',
      'no-unused-vars': 'off',
    },
  },
  ...vue.configs['flat/essential'],
  {
    // File-based routing intentionally uses index.vue and [id].vue.
    rules: { 'vue/multi-word-component-names': 'off' },
  },
  {
    files: ['**/*.ts'],
    languageOptions: { parser: ts.parser },
    plugins: { '@typescript-eslint': ts.plugin },
    rules: {
      'no-redeclare': 'off',
      '@typescript-eslint/no-redeclare': 'error',
      '@typescript-eslint/no-duplicate-enum-values': 'error',
      '@typescript-eslint/no-misused-new': 'error',
      '@typescript-eslint/no-non-null-asserted-optional-chain': 'error',
    },
  },
  {
    files: ['**/*.vue'],
    languageOptions: { parserOptions: { parser: ts.parser } },
  },
  {
    files: ['core/websocket.ts', 'app/process/stores/processStore.ts', 'app/process/composables/useProcessRunActions.ts'],
    languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } },
    rules: {
      '@typescript-eslint/no-floating-promises': ['error', { ignoreVoid: true }],
      '@typescript-eslint/no-misused-promises': 'error',
    },
  },
]
