import type { AdminRole } from './session'

export interface LoginResult {
  access_token: string
  expires_in?: number
  role: AdminRole
  username?: string
}

export interface ModelPrice {
  model: string
  in_hit_per_m: number
  in_miss_per_m: number
  out_per_m: number
  thinking: 'enabled' | 'disabled'
  max_tokens_cap: number
  enabled: boolean
  version: number
  updated_at?: string
}

export interface PriceHistoryEntry {
  id?: number
  model: string
  version: number
  in_hit_per_m: number
  in_miss_per_m: number
  out_per_m: number
  enabled: boolean
  admin_id: number
  reason: string
  created_at: string
}

export interface PackageItem {
  id: number
  name: string
  description: string
  price_cents: number
  credits: number
  enabled: boolean
  sort_order: number
  updated_at?: string
}

export type OrderStatus = 'pending' | 'paid' | 'credited' | 'cancelled'

export interface OrderItem {
  id: number
  user_id: number
  phone_mask?: string
  package_name: string
  price_cents: number
  credits: number
  status: OrderStatus
  channel: string
  trade_no?: string | null
  created_at: string
  paid_at?: string | null
}

export interface UserItem {
  id: number
  phone_mask: string
  balance: number
  held: number
  created_at?: string
}

export interface LedgerItem {
  id: number
  type: string
  amount: number
  request_id?: string
  ref?: string | null
  balance_after: number
  held_after: number
  created_at: string
}

export interface GrantPayload {
  phone?: string
  user_id?: number
  amount: number
  reason: string
  request_id: string
}

export interface UsageSummaryItem {
  model: string
  requests: number
  in_hit: number
  in_miss: number
  out: number
  cost: number
}

export interface NotifyLogItem {
  id: number
  user_id: number
  channel: string
  template_id: string
  status: string
  created_at: string
}

export interface ListResponse<T> {
  items: T[]
  next_cursor?: string | null
}

export type ReportStatus = 'pending' | 'notified' | 'downloaded'

export interface ReportItem {
  id: number
  user_id: number
  phone_mask: string
  title: string
  version: number
  filename: string
  size_bytes: number
  status: ReportStatus
  created_at: string
  updated_at: string
  notified_at?: string | null
  downloaded_at?: string | null
  read_at?: string | null
}

export interface ReportVersionItem {
  version: number
  filename: string
  content_type: string
  size_bytes: number
  uploaded_by: number
  created_at: string
}

export interface ReportDetail extends ReportItem {
  versions: ReportVersionItem[]
}

export interface ReportListResponse {
  items: ReportItem[]
  total: number
}
