import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const proxyTarget = process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8899'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/admin': { target: proxyTarget, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    environmentOptions: {
      jsdom: {
        url: 'http://localhost:3000/',
      },
    },
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.test.{ts,tsx}'],
    fileParallelism: false,
    testTimeout: 120000,
  },
})
