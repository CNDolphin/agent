import { http, HttpResponse } from 'msw'
import type {
  LedgerItem,
  ModelPrice,
  NotifyLogItem,
  OrderItem,
  PackageItem,
  PriceHistoryEntry,
  ReportItem,
  UsageSummaryItem,
  UserItem,
} from '../api/types'

interface RecordedRequest {
  method: string
  path: string
  body?: unknown
}

interface MockData {
  prices: ModelPrice[]
  priceHistory: Record<string, PriceHistoryEntry[]>
  packages: PackageItem[]
  orders: OrderItem[]
  users: UserItem[]
  ledger: LedgerItem[]
  usage: UsageSummaryItem[]
  notifyLogs: NotifyLogItem[]
  reports: ReportItem[]
  requests: RecordedRequest[]
}

function initialPrices(): ModelPrice[] {
  return [
    {
      model: 'deepseek-flash',
      in_hit_per_m: 200,
      in_miss_per_m: 2000,
      out_per_m: 8000,
      thinking: 'disabled',
      max_tokens_cap: 2048,
      enabled: true,
      version: 3,
      updated_at: '2026-11-01T02:00:00Z',
    },
    {
      model: 'deepseek-v4-pro',
      in_hit_per_m: 300,
      in_miss_per_m: 3000,
      out_per_m: 12000,
      thinking: 'disabled',
      max_tokens_cap: 4096,
      enabled: false,
      version: 1,
      updated_at: '2026-10-20T02:00:00Z',
    },
  ]
}

function initialPriceHistory(): Record<string, PriceHistoryEntry[]> {
  return {
    'deepseek-flash': [
      {
        id: 11,
        model: 'deepseek-flash',
        version: 3,
        in_hit_per_m: 200,
        in_miss_per_m: 2000,
        out_per_m: 8000,
        enabled: true,
        admin_id: 1,
        reason: '按上游成本初始化',
        created_at: '2026-11-01T02:00:00Z',
      },
    ],
  }
}

function initialPackages(): PackageItem[] {
  return [
    {
      id: 1,
      name: '体验包',
      description: '首次体验',
      price_cents: 990,
      credits: 100,
      enabled: true,
      sort_order: 1,
    },
    {
      id: 2,
      name: '标准包',
      description: '日常使用',
      price_cents: 2990,
      credits: 500,
      enabled: false,
      sort_order: 2,
    },
  ]
}

function initialOrders(): OrderItem[] {
  return [
    {
      id: 1,
      user_id: 1001,
      phone_mask: '138****1234',
      package_name: '体验包',
      price_cents: 990,
      credits: 100,
      status: 'pending',
      channel: 'manual',
      created_at: '2026-11-05T03:00:00Z',
    },
    {
      id: 2,
      user_id: 1002,
      phone_mask: '139****5678',
      package_name: '标准包',
      price_cents: 2990,
      credits: 500,
      status: 'credited',
      channel: 'manual',
      created_at: '2026-11-04T03:00:00Z',
    },
  ]
}

function initialUsers(): UserItem[] {
  return [
    {
      id: 1001,
      phone_mask: '138****1234',
      balance: 100,
      held: 20,
      created_at: '2026-10-30T03:00:00Z',
    },
  ]
}

function initialLedger(): LedgerItem[] {
  return [
    {
      id: 2,
      type: 'grant',
      amount: 100,
      request_id: 'signup:1001',
      balance_after: 100,
      held_after: 0,
      created_at: '2026-10-30T03:00:00Z',
    },
    {
      id: 3,
      type: 'consume',
      amount: 6,
      request_id: 'chat-1',
      balance_after: 94,
      held_after: 0,
      created_at: '2026-10-31T03:00:00Z',
    },
  ]
}

function initialUsage(): UsageSummaryItem[] {
  return [
    { model: 'deepseek-flash', requests: 12, in_hit: 1000, in_miss: 2000, out: 500, cost: 42 },
  ]
}

function initialNotifyLogs(): NotifyLogItem[] {
  return [
    {
      id: 1,
      user_id: 1001,
      channel: 'sms',
      template_id: 'crisis_contact_v1',
      status: 'sent',
      created_at: '2026-11-02T03:00:00Z',
    },
  ]
}

function initialReports(): ReportItem[] {
  return [
    {
      id: 1,
      user_id: 1001,
      phone_mask: '138****1234',
      title: '心理测评报告',
      version: 2,
      filename: 'report-v2.pdf',
      size_bytes: 204800,
      status: 'downloaded',
      created_at: '2026-11-05T03:00:00Z',
      updated_at: '2026-11-06T03:00:00Z',
      notified_at: '2026-11-06T03:00:00Z',
      downloaded_at: '2026-11-06T04:00:00Z',
      read_at: '2026-11-06T05:00:00Z',
    },
    {
      id: 2,
      user_id: 1002,
      phone_mask: '139****5678',
      title: '焦虑自评量表',
      version: 1,
      filename: 'anxiety.pdf',
      size_bytes: 51200,
      status: 'pending',
      created_at: '2026-11-07T03:00:00Z',
      updated_at: '2026-11-07T03:00:00Z',
    },
  ]
}

export const mockData: MockData = {
  prices: initialPrices(),
  priceHistory: initialPriceHistory(),
  packages: initialPackages(),
  orders: initialOrders(),
  users: initialUsers(),
  ledger: initialLedger(),
  usage: initialUsage(),
  notifyLogs: initialNotifyLogs(),
  reports: initialReports(),
  requests: [],
}

export function resetMockData(): void {
  mockData.prices = initialPrices()
  mockData.priceHistory = initialPriceHistory()
  mockData.packages = initialPackages()
  mockData.orders = initialOrders()
  mockData.users = initialUsers()
  mockData.ledger = initialLedger()
  mockData.usage = initialUsage()
  mockData.notifyLogs = initialNotifyLogs()
  mockData.reports = initialReports()
  mockData.requests = []
}

function record(method: string, path: string, body?: unknown): void {
  mockData.requests.push({ method, path, body })
}

export const handlers = [
  http.post('*/admin/auth/login', async ({ request }) => {
    const body = (await request.json()) as { username?: string; password?: string }
    record('POST', '/admin/auth/login', body)
    if (body.username === 'admin' && body.password === 'admin123') {
      return HttpResponse.json({
        access_token: 'token-super',
        expires_in: 900,
        role: 'super',
        username: 'admin',
      })
    }
    if (body.username === 'ops' && body.password === 'ops123') {
      return HttpResponse.json({
        access_token: 'token-ops',
        expires_in: 900,
        role: 'ops',
        username: 'ops',
      })
    }
    return HttpResponse.json(
      { code: 40101, message: '用户名或密码错误' },
      { status: 401 },
    )
  }),

  http.get('*/admin/prices', () => HttpResponse.json({ items: mockData.prices })),

  http.get('*/admin/prices/:model/history', ({ params }) => {
    const model = String(params.model)
    return HttpResponse.json({ items: mockData.priceHistory[model] ?? [] })
  }),

  http.put('*/admin/prices/:model', async ({ params, request }) => {
    const model = String(params.model)
    const body = (await request.json()) as Record<string, unknown>
    record('PUT', `/admin/prices/${model}`, body)
    const existing = mockData.prices.find((item) => item.model === model)
    const updated: ModelPrice = {
      model,
      in_hit_per_m: Number(body.in_hit_per_m ?? 0),
      in_miss_per_m: Number(body.in_miss_per_m ?? 0),
      out_per_m: Number(body.out_per_m ?? 0),
      thinking: body.thinking === 'enabled' ? 'enabled' : 'disabled',
      max_tokens_cap: Number(body.max_tokens_cap ?? 0),
      enabled: Boolean(body.enabled),
      version: (existing?.version ?? 0) + 1,
      updated_at: '2026-11-06T00:00:00Z',
    }
    mockData.prices = mockData.prices.map((item) =>
      item.model === model ? updated : item,
    )
    return HttpResponse.json(updated)
  }),

  http.get('*/admin/packages', () => HttpResponse.json({ items: mockData.packages })),

  http.post('*/admin/packages', async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>
    record('POST', '/admin/packages', body)
    const created: PackageItem = {
      id: mockData.packages.length + 1,
      name: String(body.name ?? ''),
      description: String(body.description ?? ''),
      price_cents: Number(body.price_cents ?? 0),
      credits: Number(body.credits ?? 0),
      enabled: Boolean(body.enabled),
      sort_order: Number(body.sort_order ?? 0),
    }
    mockData.packages = [...mockData.packages, created]
    return HttpResponse.json(created)
  }),

  http.put('*/admin/packages/:id', async ({ params, request }) => {
    const id = Number(params.id)
    const body = (await request.json()) as Record<string, unknown>
    record('PUT', `/admin/packages/${id}`, body)
    mockData.packages = mockData.packages.map((item) =>
      item.id === id
        ? {
            ...item,
            name: String(body.name ?? item.name),
            description: String(body.description ?? item.description),
            price_cents: Number(body.price_cents ?? item.price_cents),
            credits: Number(body.credits ?? item.credits),
            sort_order: Number(body.sort_order ?? item.sort_order),
            enabled: Boolean(body.enabled ?? item.enabled),
          }
        : item,
    )
    const updated = mockData.packages.find((item) => item.id === id)
    return HttpResponse.json(updated ?? {})
  }),

  http.get('*/admin/orders', ({ request }) => {
    const url = new URL(request.url)
    const status = url.searchParams.get('status')
    const items = status ? mockData.orders.filter((item) => item.status === status) : mockData.orders
    return HttpResponse.json({ items })
  }),

  http.post('*/admin/orders/:id/confirm', ({ params }) => {
    const id = Number(params.id)
    record('POST', `/admin/orders/${id}/confirm`)
    mockData.orders = mockData.orders.map((item) =>
      item.id === id ? { ...item, status: 'credited' as const } : item,
    )
    return HttpResponse.json(mockData.orders.find((item) => item.id === id) ?? {})
  }),

  http.post('*/admin/orders/:id/cancel', ({ params }) => {
    const id = Number(params.id)
    record('POST', `/admin/orders/${id}/cancel`)
    mockData.orders = mockData.orders.map((item) =>
      item.id === id ? { ...item, status: 'cancelled' as const } : item,
    )
    return HttpResponse.json(mockData.orders.find((item) => item.id === id) ?? {})
  }),

  http.get('*/admin/users', () =>
    HttpResponse.json({ items: mockData.users }),
  ),

  http.get('*/admin/users/:id/ledger', () =>
    HttpResponse.json({ items: mockData.ledger, next_cursor: null }),
  ),

  http.post('*/admin/credits/grant', async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>
    record('POST', '/admin/credits/grant', body)
    return HttpResponse.json({ request_id: String(body.request_id ?? '') })
  }),

  http.get('*/admin/usage/summary', () => HttpResponse.json({ items: mockData.usage })),

  http.get('*/admin/notify-logs', () => HttpResponse.json({ items: mockData.notifyLogs })),

  http.get('*/admin/reports', ({ request }) => {
    const url = new URL(request.url)
    record('GET', '/admin/reports')
    const phone = url.searchParams.get('phone') ?? ''
    const keyword = url.searchParams.get('keyword') ?? ''
    const status = url.searchParams.get('status') ?? ''
    let items = [...mockData.reports]
    if (phone) {
      items = items.filter((item) => item.phone_mask.endsWith(phone.slice(-4)))
    }
    if (keyword) {
      items = items.filter(
        (item) => item.title.includes(keyword) || item.filename.includes(keyword),
      )
    }
    if (status) {
      items = items.filter((item) => item.status === status)
    }
    return HttpResponse.json({ items, total: items.length })
  }),

  http.get('*/admin/reports/:id/download', () =>
    new HttpResponse(new Blob(['%PDF-1.4 mock']), {
      headers: { 'Content-Type': 'application/pdf' },
    }),
  ),

  http.get('*/admin/reports/:id', ({ params }) => {
    const id = Number(params.id)
    const item = mockData.reports.find((report) => report.id === id)
    if (!item) {
      return HttpResponse.json({ code: 40402, message: '检测报告不存在' }, { status: 404 })
    }
    return HttpResponse.json({
      ...item,
      versions: [
        {
          version: item.version,
          filename: item.filename,
          content_type: 'application/pdf',
          size_bytes: item.size_bytes,
          uploaded_by: 1,
          created_at: item.updated_at,
        },
      ],
    })
  }),

  http.post('*/admin/reports', async ({ request }) => {
    const form = await request.formData()
    const file = form.get('file')
    const filename = file && typeof file === 'object' && 'name' in file ? String(file.name) : 'report.pdf'
    record('POST', '/admin/reports', {
      userId: form.get('user_id'),
      title: form.get('title'),
      filename,
    })
    const created: ReportItem = {
      id: mockData.reports.length + 100,
      user_id: Number(form.get('user_id') ?? 0),
      phone_mask: '138****1234',
      title: String(form.get('title') || filename),
      version: 1,
      filename,
      size_bytes: file && typeof file === 'object' && 'size' in file ? Number(file.size) : 0,
      status: 'pending',
      created_at: '2026-11-08T03:00:00Z',
      updated_at: '2026-11-08T03:00:00Z',
    }
    mockData.reports = [created, ...mockData.reports]
    return HttpResponse.json(created)
  }),

  http.post('*/admin/reports/:id/versions', ({ params }) => {
    const id = Number(params.id)
    record('POST', `/admin/reports/${id}/versions`)
    mockData.reports = mockData.reports.map((item) =>
      item.id === id
        ? { ...item, version: item.version + 1, status: 'pending' as const, downloaded_at: null, read_at: null }
        : item,
    )
    return HttpResponse.json(mockData.reports.find((item) => item.id === id) ?? {})
  }),

  http.post('*/admin/reports/:id/notify', ({ params }) => {
    const id = Number(params.id)
    record('POST', `/admin/reports/${id}/notify`)
    mockData.reports = mockData.reports.map((item) =>
      item.id === id ? { ...item, notified_at: '2026-11-09T03:00:00Z' } : item,
    )
    return HttpResponse.json(mockData.reports.find((item) => item.id === id) ?? {})
  }),

  http.delete('*/admin/reports/:id', ({ params }) => {
    const id = Number(params.id)
    record('DELETE', `/admin/reports/${id}`)
    mockData.reports = mockData.reports.filter((item) => item.id !== id)
    return new HttpResponse(null, { status: 204 })
  }),
]
