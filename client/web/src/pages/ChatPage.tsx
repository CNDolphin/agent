import { Alert, Button, Card, Input, Modal, Radio, Space, Tag, Tooltip, Typography } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError, api, errorMessage } from '../api'
import { CrisisCard } from '../components/CrisisCard'
import { useSpeechRecognition, useSpeechSynthesis } from '../voice'
import type {
  ChatReply,
  CreditBalance,
  OnboardingState,
  ReportUploadResult,
  SessionDetail,
  SessionSummary,
} from '../types'
import { notifyReportsUpdated } from './ReportsPage'

interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
}

let messageSeq = 0

function nextMessageId(): string {
  messageSeq += 1
  return `msg-${Date.now()}-${messageSeq}`
}

const INTRO =
  '你好,我是你的本地心理助手。你可以在这里说说最近的感受,也可以让我陪你做一次量表筛查或放松练习。\n' +
  '我不是医生,提供的只是筛查提示与自助支持;如果情况紧急,请拨打 12356 或 120。'

const REPORT_SUFFIXES = ['.pdf', '.docx', '.txt']
const MAX_REPORT_BYTES = 20 * 1024 * 1024

function PlayIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8 5v14l11-7z" />
    </svg>
  )
}

function PlayingBars() {
  return (
    <span className="speech-bars" aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  )
}

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = String(reader.result || '')
      const comma = result.indexOf(',')
      resolve(comma >= 0 ? result.slice(comma + 1) : result)
    }
    reader.onerror = () => reject(new Error('读取文件失败,请重试'))
    reader.readAsDataURL(file)
  })
}

export function ChatPage() {
  const navigate = useNavigate()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([
    { id: nextMessageId(), role: 'assistant', text: INTRO },
  ])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [reportDialog, setReportDialog] = useState(false)
  const [reportMode, setReportMode] = useState<'revise' | 'archive'>('revise')
  const reviseRef = useRef(false)
  const [crisis, setCrisis] = useState(false)
  const [balance, setBalance] = useState<CreditBalance | null>(null)
  const [error, setError] = useState('')
  const [voiceError, setVoiceError] = useState<{ message: string; code: string } | null>(null)
  const [voiceNotice, setVoiceNotice] = useState('')
  const [openingSettings, setOpeningSettings] = useState(false)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)
  // 本轮听写开始前的已有文本,语音转写结果追加在它后面。
  const voicePrefixRef = useRef('')

  const speech = useSpeechRecognition({
    onTranscript: (transcript) => {
      setInput(`${voicePrefixRef.current}${transcript}`)
    },
    onError: (message, code) => setVoiceError({ message, code }),
  })
  const tts = useSpeechSynthesis()

  const needsSettings =
    voiceError !== null &&
    (voiceError.code === 'not-allowed' || voiceError.code === 'service-not-allowed')

  const goOnboarding = useCallback(() => {
    navigate('/onboarding', { replace: true })
  }, [navigate])

  const openSession = useCallback(async (target: string) => {
    tts.stop()
    const detail = await api.get<SessionDetail>(`/sessions/${target}`)
    const history: Message[] = detail.messages.map((item) => ({
      id: nextMessageId(),
      role: item.role,
      text: item.text,
    }))
    setSessionId(detail.session_id)
    setMessages(
      history.length
        ? history
        : [{ id: nextMessageId(), role: 'assistant', text: INTRO }],
    )
  }, [tts.stop])

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

  function toggleVoice() {
    if (speech.listening) {
      speech.stop()
      return
    }
    setVoiceError(null)
    setVoiceNotice('')
    voicePrefixRef.current = input
    speech.start()
  }

  async function openMicSettings() {
    setOpeningSettings(true)
    try {
      const result = await api.post<{ ok: boolean; host_app?: string | null }>(
        '/system/open-microphone-settings',
      )
      const host = result.host_app
      setVoiceError(null)
      setVoiceNotice(
        host
          ? `已打开系统设置。macOS 把麦克风权限记在启动本应用的「${host}」名下,请勾选它;如果列表里没有,请再点一次「语音输入」触发授权弹窗,授权后重启应用。`
          : '已打开系统设置,请在麦克风列表中勾选启动本应用的终端程序;如果列表里没有,请再点一次「语音输入」触发授权弹窗,授权后重启应用。',
      )
    } catch (err) {
      setVoiceError({ message: errorMessage(err), code: 'open_failed' })
    } finally {
      setOpeningSettings(false)
    }
  }

  async function send() {
    const text = input.trim()
    if (!text || sending || uploading) return
    speech.stop()
    tts.stop()
    setVoiceNotice('')
    setMessages((items) => [...items, { id: nextMessageId(), role: 'user', text }])
    setInput('')
    setSending(true)
    setError('')
    try {
      const data = await api.post<ChatReply>('/chat', {
        text,
        ...(sessionId ? { session_id: sessionId } : {}),
      })
      if (!sessionId) setSessionId(data.session_id)
      const replyId = nextMessageId()
      setMessages((items) => [...items, { id: replyId, role: 'assistant', text: data.reply }])
      tts.speak(replyId, data.reply)
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

  function openReportDialog() {
    if (sending || uploading) return
    setReportMode('revise')
    setReportDialog(true)
  }

  function chooseReportFile() {
    reviseRef.current = reportMode === 'revise'
    setReportDialog(false)
    fileRef.current?.click()
  }

  async function submitReport(file: File) {
    const reset = () => {
      if (fileRef.current) fileRef.current.value = ''
    }
    const lower = file.name.toLowerCase()
    const suffix = lower.slice(lower.lastIndexOf('.'))
    if (!REPORT_SUFFIXES.includes(suffix)) {
      setError('只支持 PDF、DOCX、TXT 格式的检测报告')
      reset()
      return
    }
    if (file.size > MAX_REPORT_BYTES) {
      setError('报告文件不能超过 20MB')
      reset()
      return
    }
    setUploading(true)
    setError('')
    try {
      const content = await readBase64(file)
      const data = await api.post<ReportUploadResult>('/reports/upload', {
        filename: file.name,
        content,
        title: file.name.replace(/\.[^.]+$/, ''),
        ...(reviseRef.current ? { revise_interpretation: true } : {}),
      })
      const note = data.interpretation?.note
      setMessages((items) => [
        ...items,
        { id: nextMessageId(), role: 'user', text: `提交报告《${file.name}》` },
        {
          id: nextMessageId(),
          role: 'assistant',
          text: note ? `${data.analysis}\n\n${note}` : data.analysis,
        },
      ])
      notifyReportsUpdated()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      reviseRef.current = false
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  function toggleSpeech(message: Message) {
    if (tts.speakingId === message.id) tts.stop()
    else tts.speak(message.id, message.text)
  }

  return (
    <div className="chat-page">
      <div className="chat-head">
        <Space direction="vertical" size={0}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            对话支持
          </Typography.Title>
          <Typography.Text type="secondary">
            内容只保存在本机;也可直接提交检测报告(PDF/DOCX/TXT),我会对比上一份与入学测评后记入长期记忆。
          </Typography.Text>
        </Space>
        <Space wrap>
          {balance && <Tag color="green">可用积分 {balance.available}</Tag>}
        </Space>
      </div>

      <Typography.Text type="secondary" className="chat-session-title">
        这是你唯一的会话,所有对话都会续在这里。
      </Typography.Text>
      {crisis && <CrisisCard />}
      {error && <Alert type="error" showIcon message={error} />}
      {voiceError && (
        <Alert
          type="warning"
          showIcon
          message={voiceError.message}
          action={
            needsSettings ? (
              <Button size="small" loading={openingSettings} onClick={() => void openMicSettings()}>
                打开设置
              </Button>
            ) : undefined
          }
        />
      )}
      {voiceNotice && <Alert type="info" showIcon message={voiceNotice} />}

      <div className="chat-body">
        {messages.map((message) => (
          <div key={message.id} className={`bubble-row ${message.role}`}>
            {message.role === 'assistant' ? (
              <div className={`bubble assistant${tts.supported ? ' with-speech' : ''}`}>
                <div className="bubble-text">{message.text}</div>
                {tts.supported && (
                  <Tooltip
                    title={tts.speakingId === message.id ? '停止朗读' : '朗读这条回复'}
                  >
                    <button
                      type="button"
                      className={`speech-toggle${
                        tts.speakingId === message.id ? ' is-playing' : ''
                      }`}
                      aria-label={
                        tts.speakingId === message.id ? '停止朗读' : '朗读这条回复'
                      }
                      onClick={() => toggleSpeech(message)}
                    >
                      {tts.speakingId === message.id ? <PlayingBars /> : <PlayIcon />}
                    </button>
                  </Tooltip>
                )}
              </div>
            ) : (
              <div className="bubble user">{message.text}</div>
            )}
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
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,.txt"
          style={{ display: 'none' }}
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void submitReport(file)
          }}
        />
        <Button
          disabled={sending || uploading}
          loading={uploading}
          onClick={openReportDialog}
        >
          提交报告
        </Button>
        {speech.supported && (
          <Tooltip title="语音识别由浏览器提供,可能需要联网">
            <Button
              aria-label={speech.listening ? '停止语音输入' : '语音输入'}
              danger={speech.listening}
              onClick={toggleVoice}
            >
              {speech.listening ? '停止听写' : '语音输入'}
            </Button>
          </Tooltip>
        )}
        <Button type="primary" loading={sending} disabled={uploading} onClick={() => void send()}>
          发送
        </Button>
      </Card>
      <Modal
        open={reportDialog}
        title="提交检测报告"
        okText="选择文件并提交"
        cancelText="取消"
        onCancel={() => setReportDialog(false)}
        onOk={chooseReportFile}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Typography.Text type="secondary">
            选择报告在本次会话中的使用方式，确认后再选择文件。
          </Typography.Text>
          <Radio.Group
            value={reportMode}
            onChange={(event) => setReportMode(event.target.value)}
          >
            <Space direction="vertical">
              <Radio value="revise">
                修正解读报告（推荐）：8 项智能分作为基因分参与融合，40 项指标覆盖原测评，
                后续对话以更新后的解读报告为准
              </Radio>
              <Radio value="archive">仅归档报告：不改动当前解读报告与对话记忆</Radio>
            </Space>
          </Radio.Group>
        </Space>
      </Modal>
    </div>
  )
}
