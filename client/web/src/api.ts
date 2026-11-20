/**
 * 本地 API 请求封装。
 *
 * 鉴权分两种来源:
 * - 桌面窗口(回环地址):页面注入 `X-Local-Token`,开发模式通过 /api/dev-token 获取;
 * - 局域网设备:用子账号用户名 + 密码登录后拿到 `X-Device-Token`,存 localStorage。
 */

let cachedLocalToken: string | null = null
let localTokenPending: Promise<string> | null = null

export const DEVICE_TOKEN_KEY = 'mhagent.device_token'

export class ApiError extends Error {
  status: number
  code: string
  data: Record<string, unknown>

  constructor(status: number, code: string, message: string, data: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.data = data
  }
}

function injectedToken(): string {
  return typeof window !== 'undefined' ? (window.__LOCAL_TOKEN__ ?? '') : ''
}

async function resolveLocalToken(): Promise<string> {
  if (cachedLocalToken !== null) return cachedLocalToken
  if (!localTokenPending) {
    localTokenPending = (async () => {
      const injected = injectedToken()
      if (injected) return injected
      // 开发模式:通过 Vite 代理从本地服务取令牌(仅回环地址可用);
      // 局域网页面没有注入令牌,这里会拿到 403,静默返回空。
      try {
        const response = await fetch('/api/dev-token')
        if (!response.ok) return ''
        const data = (await response.json()) as { token?: string }
        return String(data.token ?? '')
      } catch {
        return ''
      }
    })().then((token) => {
      cachedLocalToken = token
      return token
    })
  }
  return localTokenPending
}

export function getDeviceToken(): string {
  try {
    return window.localStorage.getItem(DEVICE_TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
}

export function setDeviceToken(token: string): void {
  try {
    window.localStorage.setItem(DEVICE_TOKEN_KEY, token)
  } catch {
    // localStorage 不可用时忽略,登录后仍可通过刷新重试。
  }
}

export function clearDeviceToken(): void {
  try {
    window.localStorage.removeItem(DEVICE_TOKEN_KEY)
  } catch {
    // 忽略。
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const url = path.startsWith('/api/') ? path : `/api${path}`
  const localToken = await resolveLocalToken()
  const deviceToken = getDeviceToken()
  let response: Response
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(localToken ? { 'X-Local-Token': localToken } : {}),
        ...(deviceToken ? { 'X-Device-Token': deviceToken } : {}),
        ...(init.headers ?? {}),
      },
    })
  } catch {
    throw new ApiError(0, 'network_error', '无法连接本地服务,请确认应用正在运行')
  }

  if (!response.ok) {
    if (response.status === 401) {
      // 设备登录失效时清理令牌,状态刷新后会自动回到登录页。
      clearDeviceToken()
    }
    let payload: Record<string, unknown> = {}
    try {
      payload = (await response.json()) as Record<string, unknown>
    } catch {
      payload = {}
    }
    throw new ApiError(
      response.status,
      String(payload.code ?? 'unknown'),
      String(payload.message ?? `请求失败(${response.status})`),
      payload,
    )
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

function filenameFromDisposition(header: string | null): string {
  if (!header) return ''
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim())
    } catch {
      return star[1].trim()
    }
  }
  const quoted = /filename="([^"]+)"/i.exec(header)
  return quoted?.[1] ?? ''
}

/** 下载本地服务的文件接口(带鉴权头),返回文件名并触发浏览器保存。 */
export async function downloadFile(path: string, fallbackName = 'download'): Promise<string> {
  const url = path.startsWith('/api/') ? path : `/api${path}`
  const localToken = await resolveLocalToken()
  const deviceToken = getDeviceToken()
  let response: Response
  try {
    response = await fetch(url, {
      headers: {
        ...(localToken ? { 'X-Local-Token': localToken } : {}),
        ...(deviceToken ? { 'X-Device-Token': deviceToken } : {}),
      },
    })
  } catch {
    throw new ApiError(0, 'network_error', '无法连接本地服务,请确认应用正在运行')
  }
  if (!response.ok) {
    if (response.status === 401) clearDeviceToken()
    let payload: Record<string, unknown> = {}
    try {
      payload = (await response.json()) as Record<string, unknown>
    } catch {
      payload = {}
    }
    throw new ApiError(
      response.status,
      String(payload.code ?? 'unknown'),
      String(payload.message ?? `下载失败(${response.status})`),
      payload,
    )
  }
  const blob = await response.blob()
  const filename =
    filenameFromDisposition(response.headers.get('Content-Disposition')) || fallbackName
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(href)
  return filename
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body ?? {}) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body ?? {}) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return '网络异常,请稍后重试'
}

export function resetTokenCache(): void {
  cachedLocalToken = null
  localTokenPending = null
}
