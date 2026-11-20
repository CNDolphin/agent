import dayjs from 'dayjs'

export function formatMoney(cents: number): string {
  return `¥${(cents / 100).toFixed(2)}`
}

export function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm:ss') : value
}

export const ORDER_STATUS_LABELS: Record<string, string> = {
  pending: '待支付',
  paid: '已支付待入账',
  credited: '已入账',
  cancelled: '已取消',
}

export const ORDER_STATUS_COLORS: Record<string, string> = {
  pending: 'gold',
  paid: 'blue',
  credited: 'green',
  cancelled: 'red',
}

export const LEDGER_TYPE_LABELS: Record<string, string> = {
  grant: '注册赠送',
  recharge: '套餐入账',
  hold: '冻结',
  release: '解冻',
  consume: '消费',
  refund: '退款',
}

export const NOTIFY_CHANNEL_LABELS: Record<string, string> = {
  sms: '短信',
  email: '邮件',
}

export const NOTIFY_STATUS_LABELS: Record<string, string> = {
  sent: '已发送',
  failed: '发送失败',
}

export function newRequestId(prefix = 'admin-grant'): string {
  const cryptoApi = globalThis.crypto
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return `${prefix}-${cryptoApi.randomUUID()}`
  }
  const seed = Math.random().toString(16).slice(2, 10)
  return `${prefix}-${Date.now()}-${seed}`
}
