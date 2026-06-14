import { defineConfig } from 'vitest/config'
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
