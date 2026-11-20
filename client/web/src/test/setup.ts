import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'

import { resetTokenCache } from '../api'
import { resetMockData } from './handlers'
import { server } from './server'

configure({ asyncUtilTimeout: 5000 })

window.__LOCAL_TOKEN__ = 'test-token'

beforeAll(() => {
  server.listen({ onUnhandledFrame: 'error' })
})

afterEach(() => {
  cleanup()
  server.resetHandlers()
  resetMockData()
  resetTokenCache()
  window.localStorage.clear()
  window.__LOCAL_TOKEN__ = 'test-token'
})

afterAll(() => {
  server.close()
})

vi.stubGlobal(
  'matchMedia',
  vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
)

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

vi.stubGlobal('ResizeObserver', ResizeObserverStub)

Object.defineProperty(window, 'scrollTo', { value: vi.fn(), writable: true })
Element.prototype.scrollIntoView = vi.fn()

// jsdom 未实现 Blob URL 与下载点击,补最小桩以覆盖报告下载逻辑。
Object.defineProperty(URL, 'createObjectURL', { value: vi.fn(() => 'blob:mock'), writable: true })
Object.defineProperty(URL, 'revokeObjectURL', { value: vi.fn(), writable: true })
HTMLAnchorElement.prototype.click = vi.fn()
