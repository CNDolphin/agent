/** 本地服务的返回结构,字段与 client/app.py 一一对应。 */

export interface Profile {
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

export interface Status {
  device_mode: 'desktop' | 'lan'
  dev_mode: boolean
  legacy_required: boolean
  logged_in: boolean
  phone_mask: string | null
  active_profile: Profile | null
  profiles: Profile[]
  consent_version: string | null
  emergency_authorized: boolean
  lan_enabled: boolean
}

export interface ConsentInfo {
  latest: { version: string; text: string }
  agreed_version: string | null
  agreed: boolean
}

export interface ContactState {
  version: string | null
  emergency_authorized: boolean
  channel: 'sms' | 'email' | null
  contact: string | null
  authorized_at: string | null
}

export interface ChatReply {
  reply: string
  state: string
  crisis: boolean
  session_id: string
}

export interface SessionSummary {
  id: number
  session_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
  preview: string
}

export interface SessionMessage {
  id: number
  role: 'user' | 'assistant'
  text: string
  created_at: string
}

export interface SessionDetail {
  id: string
  session_id: string
  title: string
  created_at: string
  updated_at: string
  messages: SessionMessage[]
}

export interface ScaleSummary {
  id: string
  name: string
  version: string
  available: boolean
  item_count: number
}

export interface ScaleOption {
  value: number
  label: string
}

export interface ScaleDetail {
  id: string
  name: string
  version: string
  intro: string
  options: ScaleOption[]
  items: string[]
  available: boolean
}

export interface AssessmentOutcome {
  scale: string
  total: number
  max_total: number
  level: string
  label: string
  advice: string | null
  high_risk: boolean
  notified: boolean
  text: string
  state: string
}

export interface PracticeSummary {
  id: string
  name: string
  summary: string
  repeat: number
  duration_seconds: number
}

export interface PracticeStep {
  instruction: string
  seconds: number
}

export interface PracticeDetail {
  id: string
  name: string
  summary: string
  steps: PracticeStep[]
  repeat: number
  duration_seconds: number
  stop_hint: string
}

export interface ReportItem {
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

export interface ReportList {
  items: ReportItem[]
  unread: number
}

export interface ReportSyncResult {
  synced: number
  items: ReportItem[]
  unread: number
}

export interface ReportReadResult {
  item: ReportItem
  unread: number
}

export interface CreditBalance {
  balance: number
  held: number
  available: number
}

export interface PackageItem {
  id: number
  name: string
  description?: string
  price_cents: number
  credits: number
}

export interface OrderItem {
  id: number
  package_id: number
  package_name: string
  price_cents: number
  credits: number
  status: string
  channel: string
  trade_no?: string
  created_at?: string
  paid_at?: string
}

export interface CreatedOrder {
  order_id: number
  status: string
  pay_params: Record<string, unknown>
}

export interface CrisisInfo {
  hotlines: { name: string; number: string }[]
  message: string
  copy_text: string
}

export interface LoginResult {
  is_new: boolean
  phone_mask: string
}

export interface DeviceLoginResult {
  device_token: string
  profile: Profile
}

export interface OnboardingIndicator {
  id: string
  name: string
  definition: string
}

export interface OnboardingIntelligence {
  id: string
  name: string
  indicators: OnboardingIndicator[]
}

export interface OnboardingQuestion {
  id: number
  indicator: string
  intelligence: string
  reverse: boolean
  text: string
}

export interface OnboardingQuestionnaire {
  version: string
  scale: { min: number; max: number; labels: string[] }
  intelligences: OnboardingIntelligence[]
  questions: OnboardingQuestion[]
}

export interface OnboardingGene {
  filename: string
  confidence: 'high' | 'medium' | 'low'
  scores: Record<string, number>
  notes: string
  uploaded_at?: string
  path?: string
}

export interface OnboardingProgress {
  done_items: number
  total_items: number
  quiz_valid: boolean
  intel_ranked: boolean
  ind_ranked: boolean
}

export interface OnboardingIntelScore {
  id: string
  name: string
  score: number
  inner: number
  rank: number
  source: string
}

export interface OnboardingIndicatorScore {
  id: string
  name: string
  intelligence: string
  quiz: number
  inner: number
  score: number
  rank: number
}

export interface OnboardingResult {
  intel: Record<string, OnboardingIntelScore>
  ind: Record<string, OnboardingIndicatorScore>
  ranking: string[]
  fusion_version: string
  gene_used: boolean
}

export interface OnboardingState {
  status: 'draft' | 'completed'
  answers: Record<string, number>
  rankings: { intel: string[]; ind: Record<string, string[]> }
  gene: OnboardingGene | null
  result: OnboardingResult | null
  memory_text: string
  progress: OnboardingProgress
  created_at?: string
  updated_at?: string
  completed_at?: string | null
}
