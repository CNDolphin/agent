import { apiRequest, downloadFile } from './client'
import type { AdminRole } from './session'
import type {
  GrantPayload,
  LedgerItem,
  ListResponse,
  LoginResult,
  ModelPrice,
  NotifyLogItem,
  OrderItem,
  PackageItem,
  PriceHistoryEntry,
  ReportDetail,
  ReportItem,
  ReportListResponse,
  UsageSummaryItem,
  UserItem,
} from './types'

interface RawLoginResult {
  access_token?: string
  token?: string
  expires_in?: number
  role?: string
  username?: string
  admin?: { id?: number; username?: string; role?: string }
}

function normalizeRole(value: string | undefined): AdminRole {
  return value === 'ops' ? 'ops' : 'super'
}

export async function login(username: string, password: string): Promise<LoginResult> {
  const raw = await apiRequest<RawLoginResult>('/admin/auth/login', {
    method: 'POST',
    body: { username, password },
  })
  const token = raw.access_token ?? raw.token
  if (!token) {
    throw new Error('登录响应缺少令牌')
  }
  return {
    access_token: token,
    expires_in: raw.expires_in,
    role: normalizeRole(raw.role ?? raw.admin?.role),
    username: raw.username ?? raw.admin?.username ?? username,
  }
}

export function listPrices(): Promise<ListResponse<ModelPrice>> {
  return apiRequest<ListResponse<ModelPrice>>('/admin/prices')
}

export function updatePrice(
  model: string,
  payload: Omit<ModelPrice, 'model' | 'version' | 'updated_at'> & { reason: string },
): Promise<ModelPrice> {
  return apiRequest<ModelPrice>(`/admin/prices/${encodeURIComponent(model)}`, {
    method: 'PUT',
    body: payload,
  })
}

export function listPriceHistory(model: string): Promise<ListResponse<PriceHistoryEntry>> {
  return apiRequest<ListResponse<PriceHistoryEntry>>(
    `/admin/prices/${encodeURIComponent(model)}/history`,
  )
}

export function listPackages(): Promise<ListResponse<PackageItem>> {
  return apiRequest<ListResponse<PackageItem>>('/admin/packages')
}

export type PackagePayload = Pick<
  PackageItem,
  'name' | 'description' | 'price_cents' | 'credits' | 'sort_order'
> & { enabled?: boolean }

export function createPackage(payload: PackagePayload): Promise<PackageItem> {
  return apiRequest<PackageItem>('/admin/packages', { method: 'POST', body: payload })
}

export function updatePackage(id: number, payload: PackagePayload): Promise<PackageItem> {
  return apiRequest<PackageItem>(`/admin/packages/${id}`, { method: 'PUT', body: payload })
}

export function listOrders(params: { status?: string; phone?: string }): Promise<ListResponse<OrderItem>> {
  return apiRequest<ListResponse<OrderItem>>('/admin/orders', { query: params })
}

export function confirmOrder(id: number): Promise<OrderItem> {
  return apiRequest<OrderItem>(`/admin/orders/${id}/confirm`, { method: 'POST' })
}

export function cancelOrder(id: number): Promise<OrderItem> {
  return apiRequest<OrderItem>(`/admin/orders/${id}/cancel`, { method: 'POST' })
}

export async function searchUsers(phone: string): Promise<ListResponse<UserItem>> {
  const data = await apiRequest<ListResponse<UserItem> | UserItem>('/admin/users', {
    query: { phone },
  })
  if ('items' in data) {
    return data
  }
  if ('phone_mask' in data) {
    return { items: [data] }
  }
  return { items: [] }
}

export function listUserLedger(
  userId: number,
  params: { cursor?: string; limit?: number },
): Promise<ListResponse<LedgerItem>> {
  return apiRequest<ListResponse<LedgerItem>>(`/admin/users/${userId}/ledger`, { query: params })
}

export function grantCredits(payload: GrantPayload): Promise<{ request_id: string }> {
  return apiRequest<{ request_id: string }>('/admin/credits/grant', {
    method: 'POST',
    body: payload,
  })
}

export function usageSummary(params: {
  from: string
  to: string
}): Promise<ListResponse<UsageSummaryItem>> {
  return apiRequest<ListResponse<UsageSummaryItem>>('/admin/usage/summary', { query: params })
}

export function listNotifyLogs(): Promise<ListResponse<NotifyLogItem>> {
  return apiRequest<ListResponse<NotifyLogItem>>('/admin/notify-logs')
}

export function listReports(params: {
  phone?: string
  keyword?: string
  status?: string
  page?: number
  page_size?: number
}): Promise<ReportListResponse> {
  return apiRequest<ReportListResponse>('/admin/reports', { query: params })
}

export function getReport(id: number): Promise<ReportDetail> {
  return apiRequest<ReportDetail>(`/admin/reports/${id}`)
}

export function uploadReport(payload: {
  phone?: string
  userId?: number
  title: string
  file: File
}): Promise<ReportItem> {
  const form = new FormData()
  if (payload.userId) {
    form.append('user_id', String(payload.userId))
  }
  if (payload.phone) {
    form.append('phone', payload.phone)
  }
  form.append('title', payload.title)
  form.append('file', payload.file)
  return apiRequest<ReportItem>('/admin/reports', { method: 'POST', form })
}

export function replaceReportVersion(id: number, file: File): Promise<ReportItem> {
  const form = new FormData()
  form.append('file', file)
  return apiRequest<ReportItem>(`/admin/reports/${id}/versions`, { method: 'POST', form })
}

export function notifyReport(id: number): Promise<ReportItem> {
  return apiRequest<ReportItem>(`/admin/reports/${id}/notify`, { method: 'POST' })
}

export function deleteReport(id: number): Promise<void> {
  return apiRequest<void>(`/admin/reports/${id}`, { method: 'DELETE' })
}

export function downloadReport(id: number, version?: number, fallbackName?: string): Promise<void> {
  return downloadFile(
    `/admin/reports/${id}/download`,
    version ? { version } : undefined,
    fallbackName ?? `report-${id}`,
  )
}

export type ContentKind = 'skills' | 'quiz' | 'rules' | 'scales' | 'app'

export interface ContentItem {
  id: number
  kind: ContentKind
  platform: string
  version: string
  filename: string
  content_type: string
  size_bytes: number
  sha256: string
  notes: string
  forced: boolean
  status: 'published' | 'offline'
  published_at: string | null
  created_at: string
}

export interface ContentListResponse {
  items: ContentItem[]
  total: number
}

export function uploadContent(payload: {
  kind: ContentKind
  version: string
  platform?: string
  notes?: string
  forced?: boolean
  file: File
}): Promise<ContentItem> {
  const form = new FormData()
  form.append('kind', payload.kind)
  form.append('version', payload.version)
  if (payload.platform) {
    form.append('platform', payload.platform)
  }
  if (payload.notes) {
    form.append('notes', payload.notes)
  }
  if (payload.forced) {
    form.append('forced', 'true')
  }
  form.append('file', payload.file)
  return apiRequest<ContentItem>('/admin/contents', { method: 'POST', form })
}

export function listContents(params: {
  kind?: string
  page?: number
  page_size?: number
}): Promise<ContentListResponse> {
  return apiRequest<ContentListResponse>('/admin/contents', { query: params })
}

export function notifyContent(id: number): Promise<ContentItem> {
  return apiRequest<ContentItem>(`/admin/contents/${id}/notify`, { method: 'POST' })
}

export function offlineContent(id: number): Promise<void> {
  return apiRequest<void>(`/admin/contents/${id}`, { method: 'DELETE' })
}

export function downloadContent(id: number, fallbackName?: string): Promise<void> {
  return downloadFile(`/admin/contents/${id}/download`, undefined, fallbackName ?? `content-${id}.zip`)
}
