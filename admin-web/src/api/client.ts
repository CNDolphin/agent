import { clearSession, getToken } from './session'

export type QueryValue = string | number | boolean | null | undefined

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  form?: FormData
  query?: Record<string, QueryValue>
}

interface ErrorPayload {
  code?: number
  message?: string
}

/**
 * 统一错误：业务错误携带后端 {code, message}；网络错误 status 为 0。
 */
export class ApiError extends Error {
  readonly code: number
  readonly status: number
  readonly isNetwork: boolean

  constructor(message: string, options: { code?: number; status: number; isNetwork?: boolean }) {
    super(message)
    this.name = 'ApiError'
    this.code = options.code ?? 0
    this.status = options.status
    this.isNetwork = options.isNetwork ?? false
  }
}

const envBase = import.meta.env.VITE_API_BASE as string | undefined

function resolveUrl(path: string, query?: Record<string, QueryValue>): string {
  const base = envBase ? envBase.replace(/\/+$/, '') : ''
  const search = new URLSearchParams()
  if (query) {
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        search.set(key, String(value))
      }
    })
  }
  const qs = search.toString()
  const raw = `${base}${path}${qs ? `?${qs}` : ''}`
  if (/^https?:\/\//i.test(raw)) {
    return raw
  }
  return `${window.location.origin}${raw}`
}

async function readPayload(response: Response): Promise<ErrorPayload | null> {
  try {
    const text = await response.text()
    if (!text) return null
    return JSON.parse(text) as ErrorPayload
  } catch {
    return null
  }
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken()
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  let payload: BodyInit | undefined
  if (options.form) {
    // 不设置 Content-Type,由浏览器补 multipart boundary。
    payload = options.form
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(options.body)
  }

  let response: Response
  try {
    response = await fetch(resolveUrl(path, options.query), {
      method: options.method ?? 'GET',
      headers,
      body: payload,
    })
  } catch {
    throw new ApiError('网络连接失败，请检查网络后重试', { status: 0, isNetwork: true })
  }

  if (response.status === 401) {
    const body = await readPayload(response)
    clearSession()
    throw new ApiError(body?.message ?? '登录已过期，请重新登录', {
      code: body?.code ?? 40101,
      status: 401,
    })
  }

  if (!response.ok) {
    const body = await readPayload(response)
    throw new ApiError(body?.message ?? `请求失败（HTTP ${response.status}）`, {
      code: body?.code ?? response.status,
      status: response.status,
    })
  }

  if (response.status === 204) {
    return undefined as T
  }

  const text = await response.text()
  if (!text) {
    return undefined as T
  }

  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiError('响应解析失败', { status: response.status })
  }
}

function filenameFromDisposition(value: string | null): string | null {
  if (!value) return null
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(value)
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1])
    } catch {
      return encoded[1]
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(value)
  return plain ? plain[1] : null
}

/**
 * 带鉴权下载文件并触发浏览器保存。用于报告等需要 Authorization 的二进制接口。
 */
export async function downloadFile(
  path: string,
  query?: Record<string, QueryValue>,
  fallbackName = 'download',
): Promise<void> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  let response: Response
  try {
    response = await fetch(resolveUrl(path, query), { headers })
  } catch {
    throw new ApiError('网络连接失败，请检查网络后重试', { status: 0, isNetwork: true })
  }

  if (response.status === 401) {
    const body = await readPayload(response)
    clearSession()
    throw new ApiError(body?.message ?? '登录已过期，请重新登录', {
      code: body?.code ?? 40101,
      status: 401,
    })
  }
  if (!response.ok) {
    const body = await readPayload(response)
    throw new ApiError(body?.message ?? `下载失败（HTTP ${response.status}）`, {
      code: body?.code ?? response.status,
      status: response.status,
    })
  }

  const blob = await response.blob()
  const filename = filenameFromDisposition(response.headers.get('Content-Disposition')) ?? fallbackName
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  anchor.rel = 'noopener'
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  // 立即回收会让 Safari 及大文件下载被取消,延迟释放并移除锚点。
  window.setTimeout(() => {
    anchor.remove()
    URL.revokeObjectURL(objectUrl)
  }, 60_000)
}
