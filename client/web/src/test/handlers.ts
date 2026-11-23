import { http, HttpResponse } from 'msw'

export interface MockOrder {
  id: number
  package_id: number
  package_name: string
  price_cents: number
  credits: number
  status: string
  channel: string
  created_at: string
  paid_at?: string
}

export interface MockProfile {
  id: string
  role: 'main' | 'sub'
  nickname: string
  username: string
  note: string
  age_range: string
  phone_mask: string
  status: 'active' | 'disabled'
  created_at: string
  updated_at: string
}

export interface MockMessage {
  id: number
  role: 'user' | 'assistant'
  text: string
  created_at: string
}

export interface MockSession {
  session_id: string
  title: string
  created_at: string
  updated_at: string
  messages: MockMessage[]
}

export interface MockReport {
  report_id: number
  version: number
  title: string
  filename: string
  path: string
  abs_path: string
  size_bytes: number
  content_type: string
  created_at: string
  downloaded_at: string
  read_at: string | null
}

export interface MockState {
  device_mode: 'desktop' | 'lan'
  legacy_required: boolean
  logged_in: boolean
  phone_mask: string | null
  consent_version: string | null
  emergency_authorized: boolean
  contact_channel: 'sms' | 'email' | null
  contact: string | null
  balance: number
  orders: MockOrder[]
  next_order_id: number
  profiles: MockProfile[]
  active_profile_id: string
  sessions: MockSession[]
  reports: MockReport[]
  pending_reports: MockReport[]
  onboarding_status: 'draft' | 'completed'
}

const NOW = '2026-11-09T06:00:00+00:00'

export const MAIN_PROFILE: MockProfile = {
  id: 'main',
  role: 'main',
  nickname: '我',
  username: '',
  note: '',
  age_range: '',
  phone_mask: '138****8000',
  status: 'active',
  created_at: NOW,
  updated_at: NOW,
}

export function makeProfile(partial: Partial<MockProfile>): MockProfile {
  return { ...MAIN_PROFILE, ...partial }
}

function createState(): MockState {
  return {
    device_mode: 'desktop',
    legacy_required: false,
    logged_in: false,
    phone_mask: null,
    consent_version: null,
    emergency_authorized: false,
    contact_channel: null,
    contact: null,
    balance: 100,
    orders: [],
    next_order_id: 1,
    profiles: [{ ...MAIN_PROFILE }],
    active_profile_id: 'main',
    sessions: [],
    reports: [],
    pending_reports: [],
    onboarding_status: 'completed',
  }
}

let state = createState()
let openSettingsCalls = 0

export function getOpenSettingsCalls(): number {
  return openSettingsCalls
}

export function resetMockData(): void {
  state = createState()
  openSettingsCalls = 0
  onboardingAnswers = {}
  onboardingRankings = { intel: [], ind: {} }
}

export function setMockState(patch: Partial<MockState>): void {
  state = { ...state, ...patch }
}

function activeProfile(): MockProfile | null {
  return state.profiles.find((item) => item.id === state.active_profile_id) ?? null
}

function unreadReports(): number {
  return state.reports.filter((item) => !item.read_at).length
}

function sessionSummary(session: MockSession, index: number) {
  const lastUser = [...session.messages].reverse().find((item) => item.role === 'user')
  return {
    id: index + 1,
    session_id: session.session_id,
    title: session.title,
    created_at: session.created_at,
    updated_at: session.updated_at,
    message_count: session.messages.length,
    preview: lastUser?.text?.slice(0, 40) ?? '',
  }
}

const CONSENT_TEXT = [
  '欢迎使用本地心理健康助手。请阅读以下说明:',
  '你的日记、量表结果、练习记录与会话内容只保存在本设备,并使用设备密钥加密;',
  '对话内容会经后端网关发送给第三方模型服务,网关不保存正文;',
  '高风险且你已单独授权时,会向你的紧急联系人发送一条通知,后端发送后不保存联系方式;',
  '本产品提供筛查提示与自助支持,不构成诊断,也不能替代专业帮助;',
  '心理援助热线 12356,急救电话 120。',
].join('\n')

const PHQ_ITEMS = [
  '做事时提不起劲或没有兴趣',
  '感到心情低落、沮丧或绝望',
  '入睡困难、睡不安稳或睡得过多',
  '感觉疲倦或没有活力',
  '食欲不振或吃太多',
  '觉得自己很糟,或觉得自己很失败,让家人失望',
  '对事物专注有困难,例如看报纸或看电视时',
  '动作或说话速度缓慢到别人已经察觉,或正好相反,烦躁或坐立不安、动来动去',
  '有不如死掉或用某种方式伤害自己的念头',
]

const GAD_ITEMS = [
  '感到紧张、焦虑或急切',
  '不能停止或控制担忧',
  '对各种各样的事情担忧过多',
  '很难放松下来',
  '由于不安而无法静坐',
  '变得容易烦恼或急躁',
  '感到似乎将有可怕的事情发生而害怕',
]

const OPTIONS = [
  { value: 0, label: '完全不会' },
  { value: 1, label: '好几天' },
  { value: 2, label: '一半以上的天数' },
  { value: 3, label: '几乎每天' },
]

const PACKAGE = {
  id: 1,
  name: '体验包',
  description: '适合轻度使用的体验套餐',
  price_cents: 990,
  credits: 100,
}

const MI_GROUPS = [
  { id: 'lang', name: '语言智能', prefix: 'l' },
  { id: 'logic', name: '逻辑数学智能', prefix: 'g' },
]

function buildQuestionnaire() {
  let nextId = 1
  const intelligences = MI_GROUPS.map((group) => ({
    id: group.id,
    name: group.name,
    indicators: Array.from({ length: 5 }, (_, index) => ({
      id: `${group.prefix}${index + 1}`,
      name: `${group.name}指标${index + 1}`,
      definition: '示例指标',
    })),
  }))
  const questions = intelligences.flatMap((intel) =>
    intel.indicators.flatMap((indicator) => {
      const positive = nextId++
      const reverse = nextId++
      return [
        {
          id: positive,
          indicator: indicator.id,
          intelligence: intel.id,
          reverse: false,
          text: `${indicator.name}正向题`,
        },
        {
          id: reverse,
          indicator: indicator.id,
          intelligence: intel.id,
          reverse: true,
          text: `${indicator.name}反向题`,
        },
      ]
    }),
  )
  return {
    version: 'test',
    scale: {
      min: 1,
      max: 5,
      labels: ['完全不符合', '比较不符合', '一半一半', '比较符合', '完全符合'],
    },
    intelligences,
    questions,
  }
}

const MI_QUESTIONNAIRE = buildQuestionnaire()

const MI_RESULT = {
  intel: {
    lang: { id: 'lang', name: '语言智能', score: 82, inner: 70, rank: 1, source: 'quiz+rank' },
    logic: {
      id: 'logic',
      name: '逻辑数学智能',
      score: 64,
      inner: 60,
      rank: 2,
      source: 'quiz+rank',
    },
  },
  ind: {},
  ranking: ['lang', 'logic'],
  fusion_version: 'FUSION-1.0',
  gene_used: false,
}

let onboardingAnswers: Record<string, number> = {}
let onboardingRankings: { intel: string[]; ind: Record<string, string[]> } = {
  intel: [],
  ind: {},
}

function onboardingPayload() {
  const done = Object.keys(onboardingAnswers).length
  return {
    status: state.onboarding_status,
    answers: onboardingAnswers,
    rankings: onboardingRankings,
    gene: null,
    result: state.onboarding_status === 'completed' ? MI_RESULT : null,
    memory_text: state.onboarding_status === 'completed' ? '基础测评记忆示例' : '',
    progress: {
      done_items: done,
      total_items: 10,
      quiz_valid: state.onboarding_status === 'completed',
      intel_ranked: onboardingRankings.intel.length > 0,
      ind_ranked: Object.keys(onboardingRankings.ind).length > 0,
    },
    created_at: NOW,
    updated_at: NOW,
    completed_at: null,
  }
}

export const handlers = [
  http.post('*/api/system/open-microphone-settings', () => {
    openSettingsCalls += 1
    return HttpResponse.json({ ok: true, host_app: '终端' })
  }),

  http.get('*/api/status', () =>
    HttpResponse.json({
      device_mode: state.device_mode,
      dev_mode: state.device_mode === 'desktop',
      legacy_required: state.legacy_required,
      logged_in: state.logged_in,
      phone_mask: state.logged_in ? state.phone_mask : null,
      active_profile: state.logged_in ? activeProfile() : null,
      profiles: state.device_mode === 'desktop' ? state.profiles : [],
      consent_version: state.logged_in ? state.consent_version : null,
      emergency_authorized: state.logged_in ? state.emergency_authorized : false,
      lan_enabled: state.device_mode === 'lan',
    }),
  ),

  http.post('*/api/auth/send-code', () => HttpResponse.json({ ok: true })),

  http.post('*/api/auth/login', async ({ request }) => {
    const body = (await request.json()) as { phone?: string; password?: string }
    if (!body.phone || !body.password) {
      return HttpResponse.json(
        { code: 'invalid_request', message: '缺少参数' },
        { status: 400 },
      )
    }
    if (body.password === 'wrong') {
      return HttpResponse.json(
        { code: 'wrong_password', message: '手机号或密码错误' },
        { status: 401 },
      )
    }
    state.logged_in = true
    state.phone_mask = '138****8000'
    return HttpResponse.json({ is_new: false, phone_mask: '138****8000' })
  }),

  http.post('*/api/auth/register', async ({ request }) => {
    const body = (await request.json()) as {
      phone?: string
      code?: string
      password?: string
    }
    if (!body.phone || !body.code || !body.password) {
      return HttpResponse.json(
        { code: 'invalid_request', message: '缺少参数' },
        { status: 400 },
      )
    }
    state.logged_in = true
    state.phone_mask = '138****8000'
    return HttpResponse.json({ is_new: true, phone_mask: '138****8000' })
  }),

  http.post('*/api/auth/reset-password', () => HttpResponse.json({ ok: true })),

  http.post('*/api/auth/logout', () => {
    state.logged_in = false
    return HttpResponse.json({ logged_in: false })
  }),

  http.get('*/api/dev/sms-code', () => HttpResponse.json({ code: '123456' })),

  http.post('*/api/device/login', async ({ request }) => {
    const body = (await request.json()) as { username?: string; password?: string }
    const profile = state.profiles.find(
      (item) => item.role === 'sub' && item.username === body.username,
    )
    if (!profile || profile.status !== 'active' || body.password === 'wrong') {
      return HttpResponse.json(
        { code: 'device_auth_required', message: '账号或密码错误' },
        { status: 401 },
      )
    }
    state.logged_in = true
    state.active_profile_id = profile.id
    return HttpResponse.json({ device_token: 'device-token', profile })
  }),

  http.post('*/api/legacy/migrate', async ({ request }) => {
    const body = (await request.json()) as { passphrase?: string }
    if (body.passphrase !== 'old-pass') {
      return HttpResponse.json(
        { code: 'invalid_passphrase', message: '旧口令错误,数据未被修改' },
        { status: 400 },
      )
    }
    state.legacy_required = false
    return HttpResponse.json({ legacy_required: false })
  }),

  http.get('*/api/profiles', () => HttpResponse.json({ items: state.profiles })),

  http.post('*/api/profiles', async ({ request }) => {
    const body = (await request.json()) as {
      nickname?: string
      username?: string
      password?: string
      note?: string
      age_range?: string
    }
    const profile = makeProfile({
      id: `p_${state.profiles.length}`,
      role: 'sub',
      nickname: body.nickname ?? '新子账号',
      username: body.username ?? '',
      note: body.note ?? '',
      age_range: body.age_range ?? '',
      phone_mask: '',
    })
    state.profiles = [...state.profiles, profile]
    return HttpResponse.json(profile)
  }),

  http.patch('*/api/profiles/:id', async ({ request, params }) => {
    const id = String(params.id)
    const body = (await request.json()) as Partial<MockProfile>
    state.profiles = state.profiles.map((profile) =>
      profile.id === id ? { ...profile, ...body, updated_at: NOW } : profile,
    )
    return HttpResponse.json(state.profiles.find((profile) => profile.id === id))
  }),

  http.delete('*/api/profiles/:id', ({ params }) => {
    state.profiles = state.profiles.filter((profile) => profile.id !== String(params.id))
    return HttpResponse.json({ ok: true })
  }),

  http.post('*/api/profiles/:id/activate', ({ params }) => {
    state.active_profile_id = String(params.id)
    return HttpResponse.json({ ok: true })
  }),

  http.get('*/api/sessions', () =>
    HttpResponse.json({
      items: state.sessions.map((session, index) => sessionSummary(session, index)),
    }),
  ),

  http.post('*/api/sessions', async ({ request }) => {
    const body = (await request.json()) as { title?: string }
    const session: MockSession = {
      session_id: `s_${state.sessions.length + 1}`,
      title: body.title || '我的会话',
      created_at: NOW,
      updated_at: NOW,
      messages: [],
    }
    state.sessions = [session, ...state.sessions]
    return HttpResponse.json(sessionSummary(session, 0))
  }),

  http.get('*/api/sessions/:id', ({ params }) => {
    const id = String(params.id)
    const session = state.sessions.find((item) => item.session_id === id)
    if (!session) {
      return HttpResponse.json(
        { code: 'session_not_found', message: '会话不存在' },
        { status: 404 },
      )
    }
    return HttpResponse.json({
      id: session.session_id,
      session_id: session.session_id,
      title: session.title,
      created_at: session.created_at,
      updated_at: session.updated_at,
      messages: session.messages,
    })
  }),

  http.patch('*/api/sessions/:id', async ({ request, params }) => {
    const body = (await request.json()) as { title?: string }
    const session = state.sessions.find((item) => item.session_id === String(params.id))
    if (!session) {
      return HttpResponse.json(
        { code: 'session_not_found', message: '会话不存在' },
        { status: 404 },
      )
    }
    session.title = body.title ?? session.title
    session.updated_at = NOW
    return HttpResponse.json({ session_id: session.session_id, title: session.title })
  }),

  http.delete('*/api/sessions/:id', ({ params }) => {
    state.sessions = state.sessions.filter(
      (item) => item.session_id !== String(params.id),
    )
    return HttpResponse.json({ ok: true })
  }),

  http.get('*/api/onboarding', () => HttpResponse.json(onboardingPayload())),

  http.get('*/api/onboarding/questionnaire', () => HttpResponse.json(MI_QUESTIONNAIRE)),

  http.put('*/api/onboarding/answers', async ({ request }) => {
    const body = (await request.json()) as { answers?: Record<string, number> }
    onboardingAnswers = { ...onboardingAnswers, ...(body.answers ?? {}) }
    return HttpResponse.json(onboardingPayload())
  }),

  http.put('*/api/onboarding/rankings', async ({ request }) => {
    const body = (await request.json()) as {
      intel?: string[]
      ind?: Record<string, string[]>
    }
    onboardingRankings = {
      intel: body.intel ?? onboardingRankings.intel,
      ind: body.ind ?? onboardingRankings.ind,
    }
    return HttpResponse.json(onboardingPayload())
  }),

  http.post('*/api/onboarding/gene', async ({ request }) => {
    const body = (await request.json()) as { filename?: string }
    return HttpResponse.json({
      gene: {
        filename: body.filename ?? 'gene.pdf',
        confidence: 'high',
        scores: { lang: 78, logic: 66 },
        notes: '示例依据',
      },
    })
  }),

  http.delete('*/api/onboarding/gene', () => HttpResponse.json({ gene: null })),

  http.post('*/api/onboarding/complete', () => {
    state.onboarding_status = 'completed'
    return HttpResponse.json({ result: MI_RESULT, memory_text: '基础测评记忆示例' })
  }),

  http.post('*/api/chat', async ({ request }) => {
    const body = (await request.json()) as { text?: string; session_id?: string }
    const text = body.text ?? ''
    const crisis = text.includes('自杀')
    let session = body.session_id
      ? state.sessions.find((item) => item.session_id === body.session_id)
      : undefined
    if (!session) {
      session = {
        session_id: `s_${state.sessions.length + 1}`,
        title: '我的会话',
        created_at: NOW,
        updated_at: NOW,
        messages: [],
      }
      state.sessions = [session, ...state.sessions]
    }
    const reply = crisis
      ? '我很在意你现在的状态,请立即拨打心理援助热线 12356 或急救电话 120,并让信任的人陪着你。'
      : '我在听,你可以慢慢说。'
    const nextId = session.messages.length + 1
    session.messages = [
      ...session.messages,
      { id: nextId, role: 'user', text, created_at: NOW },
      { id: nextId + 1, role: 'assistant', text: reply, created_at: NOW },
    ]
    session.updated_at = NOW
    return HttpResponse.json({
      reply,
      state: crisis ? 'CRISIS' : 'NORMAL',
      crisis,
      session_id: session.session_id,
    })
  }),

  http.get('*/api/consents/latest', () =>
    HttpResponse.json({
      latest: { version: 'v1', text: CONSENT_TEXT },
      agreed_version: state.consent_version,
      agreed: state.consent_version === 'v1',
    }),
  ),

  http.post('*/api/consents/agree', async ({ request }) => {
    const body = (await request.json()) as { version?: string }
    state.consent_version = body.version ?? 'v1'
    return HttpResponse.json({
      ok: true,
      consent: {
        version: state.consent_version,
        emergency_authorized: state.emergency_authorized,
        channel: state.contact_channel,
        contact: state.contact,
        authorized_at: null,
      },
    })
  }),

  http.get('*/api/contact', () =>
    HttpResponse.json({
      version: state.consent_version,
      emergency_authorized: state.emergency_authorized,
      channel: state.contact_channel,
      contact: state.contact,
      authorized_at: null,
    }),
  ),

  http.post('*/api/contact', async ({ request }) => {
    const body = (await request.json()) as {
      channel?: 'sms' | 'email'
      value?: string
      authorized?: boolean
    }
    state.contact_channel = body.channel ?? 'sms'
    state.contact = body.value ?? null
    state.emergency_authorized = Boolean(body.authorized)
    return HttpResponse.json({
      version: state.consent_version,
      emergency_authorized: state.emergency_authorized,
      channel: state.contact_channel,
      contact: state.contact,
      authorized_at: null,
    })
  }),

  http.delete('*/api/contact', () => {
    state.emergency_authorized = false
    return HttpResponse.json({
      version: state.consent_version,
      emergency_authorized: false,
      channel: state.contact_channel,
      contact: state.contact,
      authorized_at: null,
    })
  }),

  http.get('*/api/scales', () =>
    HttpResponse.json({
      items: [
        { id: 'phq9', name: 'PHQ-9 抑郁筛查', version: '1', available: true, item_count: 9 },
        { id: 'gad7', name: 'GAD-7 焦虑筛查', version: '1', available: true, item_count: 7 },
        { id: 'pss10', name: 'PSS-10 压力感知量表', version: '1', available: false, item_count: 0 },
      ],
    }),
  ),

  http.get('*/api/scales/:scale', ({ params }) => {
    const scale = String(params.scale)
    const items = scale === 'phq9' ? PHQ_ITEMS : scale === 'gad7' ? GAD_ITEMS : []
    return HttpResponse.json({
      id: scale,
      name:
        scale === 'phq9'
          ? 'PHQ-9 抑郁筛查'
          : scale === 'gad7'
            ? 'GAD-7 焦虑筛查'
            : 'PSS-10 压力感知量表',
      version: '1',
      intro: '请按最近两周的真实情况作答。',
      options: OPTIONS,
      items,
      available: items.length > 0,
    })
  }),

  http.post('*/api/scales/:scale/submit', async ({ request, params }) => {
    const scale = String(params.scale)
    const body = (await request.json()) as { answers?: number[] }
    const answers = body.answers ?? []
    const total = answers.reduce((sum, value) => sum + value, 0)
    const highRisk = scale === 'phq9' && (answers[8] ?? 0) > 0
    return HttpResponse.json({
      scale,
      total,
      max_total: scale === 'phq9' ? 27 : 21,
      level: highRisk ? 'severe' : 'minimal',
      label: highRisk ? '重度' : '极轻微',
      advice: highRisk
        ? '建议尽快联系专业机构或医生;如果出现伤害自己的想法,请立即拨打 12356 或 120。'
        : '当前筛查分数较低,可以继续保持规律作息。',
      high_risk: highRisk,
      notified: highRisk && state.emergency_authorized,
      text: highRisk
        ? '筛查提示:总分偏高,请立即拨打 12356 或 120。'
        : '筛查提示:总分较低。',
      state: highRisk ? 'CRISIS' : 'NORMAL',
    })
  }),

  http.get('*/api/practices', () =>
    HttpResponse.json({
      items: [
        {
          id: 'breathing_478',
          name: '4-7-8 呼吸',
          summary: '用较长呼气帮助身体慢下来。',
          repeat: 4,
          duration_seconds: 76,
        },
      ],
    }),
  ),

  http.get('*/api/practices/:id', ({ params }) =>
    HttpResponse.json({
      id: String(params.id),
      name: '4-7-8 呼吸',
      summary: '用较长呼气帮助身体慢下来。',
      steps: [
        { instruction: '用鼻子轻轻吸气,心里数 1 到 4', seconds: 4 },
        { instruction: '屏住呼吸,心里数 1 到 7', seconds: 7 },
        { instruction: '用嘴缓缓呼气,心里数 1 到 8', seconds: 8 },
      ],
      repeat: 4,
      duration_seconds: 76,
      stop_hint: '如果出现头晕、胸闷或明显不适,请立即停止。',
    }),
  ),

  http.get('*/api/credits', () =>
    HttpResponse.json({ balance: state.balance, held: 0, available: state.balance }),
  ),

  http.get('*/api/packages', () => HttpResponse.json({ items: [PACKAGE] })),

  http.get('*/api/orders', () => HttpResponse.json({ items: state.orders })),

  http.post('*/api/orders', async ({ request }) => {
    const body = (await request.json()) as { package_id?: number; channel?: string }
    const order: MockOrder = {
      id: state.next_order_id++,
      package_id: body.package_id ?? 1,
      package_name: PACKAGE.name,
      price_cents: PACKAGE.price_cents,
      credits: PACKAGE.credits,
      status: 'pending',
      channel: body.channel ?? 'mock',
      created_at: '2026-11-06T10:00:00Z',
    }
    state.orders = [order, ...state.orders]
    return HttpResponse.json({ order_id: order.id, status: order.status, pay_params: {} })
  }),

  http.post('*/api/orders/:id/mock-pay', ({ params }) => {
    const id = Number(params.id)
    const order = state.orders.find((item) => item.id === id)
    if (!order) {
      return HttpResponse.json({ code: 'not_found', message: '订单不存在' }, { status: 404 })
    }
    order.status = 'paid'
    order.paid_at = '2026-11-06T10:01:00Z'
    state.balance += order.credits
    return HttpResponse.json({ status: 'paid', order_id: id })
  }),

  http.get('*/api/reports', () =>
    HttpResponse.json({ items: state.reports, unread: unreadReports() }),
  ),

  http.get('*/api/reports/unread-count', () =>
    HttpResponse.json({ count: unreadReports() }),
  ),

  http.post('*/api/reports/sync', () => {
    const synced = state.pending_reports.length
    state.reports = [...state.pending_reports, ...state.reports]
    state.pending_reports = []
    return HttpResponse.json({ synced, items: state.reports, unread: unreadReports() })
  }),

  http.get('*/api/reports/:id/file', ({ params }) => {
    const report = state.reports.find((item) => item.report_id === Number(params.id))
    if (!report) {
      return HttpResponse.json({ code: 'report_not_found', message: '报告不存在' }, { status: 404 })
    }
    return new HttpResponse('report-body', {
      headers: {
        'Content-Type': 'application/pdf',
        'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent(report.filename)}`,
      },
    })
  }),

  http.post('*/api/reports/:id/read', ({ params }) => {
    const report = state.reports.find((item) => item.report_id === Number(params.id))
    if (!report) {
      return HttpResponse.json({ code: 'report_not_found', message: '报告不存在' }, { status: 404 })
    }
    report.read_at = NOW
    return HttpResponse.json({ item: report, unread: unreadReports() })
  }),

  http.get('*/api/crisis', () =>
    HttpResponse.json({
      hotlines: [
        { name: '心理援助热线', number: '12356' },
        { name: '急救电话', number: '120' },
      ],
      message: '如果你现在有伤害自己的念头,请立即拨打 12356 或 120。',
      copy_text: '我现在状态很不好,需要你陪着我。如果联系不上我,请帮我拨打 12356 或 120。',
    }),
  ),
]
