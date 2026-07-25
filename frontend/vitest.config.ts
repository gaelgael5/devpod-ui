import { defineConfig, configDefaults } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
    passWithNoTests: true,
    maxWorkers: 1,
    // Les specs Playwright (e2e/) ont leur propre runner : importées par vitest
    // elles crashent au `test.describe` et polluent le signal en 8 FAIL constants.
    exclude: [...configDefaults.exclude, 'e2e/**'],
    // Stub CSS imports that Vitest cannot transform (e.g. @xterm/xterm/css/xterm.css)
    moduleNameMapper: {
      '\\.css$': path.resolve(__dirname, 'src/test/cssStub.ts'),
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      'lucide-react': path.resolve(__dirname, 'node_modules/lucide-react/dist/esm/lucide-react.mjs'),
    },
  },
})
