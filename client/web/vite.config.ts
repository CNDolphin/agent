import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const proxyTarget = process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8770'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5198,
    proxy: {
      '/api': { target: proxyTarget, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    environmentOptions: {
      jsdom: {
        url: 'http://localhost:5198/',
      },
    },
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.test.{ts,tsx}'],
    fileParallelism: false,
    // 机器负载高时单个用例可能超过 2 分钟,放宽到 5 分钟避免误报超时。
    testTimeout: 300000,
  },
})
