import { Alert, Button, Card, Input, Space, Tag, Typography } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError, api, errorMessage } from '../api'
import { CrisisCard } from '../components/CrisisCard'
import type {
  ChatReply,
  CreditBalance,
  OnboardingState,
  SessionDetail,
  SessionSummary,
} from '../types'

interface Message {
  role: 'user' | 'assistant'
  text: string
}

const INTRO =
  '你好,我是你的本地心理助手。你可以在这里说说最近的感受,也可以让我陪你做一次量表筛查或放松练习。\n' +
  '我不是医生,提供的只是筛查提示与自助支持;如果情况紧急,请拨打 12356 或 120。'

export function ChatPage() {
  const navigate = useNavigate()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [title, setTitle] = useState('我的会话')
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [messages, setMessages] = useState<Message[]>([{ role: 'assistant', text: INTRO }])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [crisis, setCrisis] = useState(false)
  const [balance, setBalance] = useState<CreditBalance | null>(null)
  const [error, setError] = useState('')
  const bottomRef = useRef<HTMLDivElement | null>(null)

  const goOnboarding = useCallback(() => {
    navigate('/onboarding', { replace: true })
  }, [navigate])

  const openSession = useCallback(async (target: string) => {
    const detail = await api.get<SessionDetail>(`/sessions/${target}`)
    const history: Message[] = detail.messages.map((item) => ({
      role: item.role,
      text: item.text,
    }))
    setSessionId(detail.session_id)
    setTitle(detail.title)
    setMessages(history.length ? history : [{ role: 'assistant', text: INTRO }])
  }, [])

  useEffect(() => {
    api
      .get<CreditBalance>('/credits')
      .then((data) => setBalance(data))
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    let cancelled = false
    async function init() {
      try {
        const onboarding = await api.get<OnboardingState>('/onboarding')
        if (cancelled) return
        if (onboarding.status !== 'completed') {
          goOnboarding()
          return
        }
        const data = await api.get<{ items: SessionSummary[] }>('/sessions')
        if (cancelled) return
        const primary = data.items[0] ?? (await api.post<SessionSummary>('/sessions', {}))
        if (cancelled) return
        await openSession(primary.session_id)
      } catch (err) {
        if (cancelled) return
        if (err instanceof ApiError && err.code === 'onboarding_required') {
          goOnboarding()
          return
        }
        setError(errorMessage(err))
      }
    }
    void init()
    return () => {
      cancelled = true
    }
  }, [goOnboarding, openSession])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  async function saveTitle() {
    const next = titleDraft.trim()
    if (!next || !sessionId) {
      setEditingTitle(false)
      return
    }
    try {
      const data = await api.patch<{ session_id: string; title: string }>(
        `/sessions/${sessionId}`,
        { title: next },
      )
      setTitle(data.title)
      setEditingTitle(false)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function send() {
    const text = input.trim()
    if (!text || sending) return
    setMessages((items) => [...items, { role: 'user', text }])
    setInput('')
    setSending(true)
    setError('')
    try {
      const data = await api.post<ChatReply>('/chat', {
        text,
        ...(sessionId ? { session_id: sessionId } : {}),
      })
      if (!sessionId) setSessionId(data.session_id)
      setMessages((items) => [...items, { role: 'assistant', text: data.reply }])
      if (data.crisis) {
        setCrisis(true)
      }
      api
        .get<CreditBalance>('/credits')
        .then((next) => setBalance(next))
        .catch(() => undefined)
    } catch (err) {
      if (err instanceof ApiError && err.status === 402) {
        setError('积分不足,可前往「积分与套餐」购买。危机热线 12356 与 120 始终可用。')
      } else if (err instanceof ApiError && err.status === 409) {
        goOnboarding()
      } else {
        setError(errorMessage(err))
      }
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="chat-page">
      <div className="chat-head">
        <Space direction="vertical" size={0}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            对话支持
          </Typography.Title>
          <Typography.Text type="secondary">
            内容只保存在本机;高风险时优先给出安全支持。
          </Typography.Text>
        </Space>
        <Space wrap>
          {editingTitle ? (
            <>
              <Input
                aria-label="会话标题"
                value={titleDraft}
                onChange={(event) => setTitleDraft(event.target.value)}
                onPressEnter={() => void saveTitle()}
                style={{ width: 200 }}
              />
              <Button type="primary" onClick={() => void saveTitle()}>
                保存
              </Button>
              <Button onClick={() => setEditingTitle(false)}>取消</Button>
            </>
          ) : (
            <>
              <Tag color="geekblue">{title}</Tag>
              <Button
                onClick={() => {
                  setTitleDraft(title)
                  setEditingTitle(true)
                }}
              >
                重命名
              </Button>
            </>
          )}
          {balance && <Tag color="green">可用积分 {balance.available}</Tag>}
        </Space>
      </div>

      <Typography.Text type="secondary" className="chat-session-title">
        这是你唯一的会话,所有对话都会续在这里。
      </Typography.Text>
      {crisis && <CrisisCard />}
      {error && <Alert type="error" showIcon message={error} />}

      <div className="chat-body">
        {messages.map((message, index) => (
          <div key={`${message.role}-${index}`} className={`bubble-row ${message.role}`}>
            <div className={`bubble ${message.role}`}>{message.text}</div>
          </div>
        ))}
        {sending && (
          <div className="bubble-row assistant">
            <div className="bubble assistant">正在思考…</div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <Card size="small" className="chat-input">
        <Input.TextArea
          aria-label="消息输入"
          autoSize={{ minRows: 1, maxRows: 4 }}
          placeholder="说说你现在想说的,Enter 发送,Shift+Enter 换行"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onPressEnter={(event) => {
            if (!event.shiftKey) {
              event.preventDefault()
              void send()
            }
          }}
        />
        <Button type="primary" loading={sending} onClick={() => void send()}>
          发送
        </Button>
      </Card>
    </div>
  )
}
