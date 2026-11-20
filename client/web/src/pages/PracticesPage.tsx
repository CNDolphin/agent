import { Alert, Button, Card, Modal, Progress, Space, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'

import { api, errorMessage } from '../api'
import type { PracticeDetail, PracticeSummary } from '../types'

export function PracticesPage() {
  const [practices, setPractices] = useState<PracticeSummary[]>([])
  const [detail, setDetail] = useState<PracticeDetail | null>(null)
  const [index, setIndex] = useState(0)
  const [round, setRound] = useState(0)
  const [remaining, setRemaining] = useState(0)
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get<{ items: PracticeSummary[] }>('/practices')
      .then((data) => setPractices(data.items))
      .catch((err) => setError(errorMessage(err)))
  }, [])

  useEffect(() => {
    if (!detail || done) return
    const seconds = detail.steps[index]?.seconds ?? 0
    setRemaining(seconds)
    if (!seconds) return
    const timer = setInterval(() => {
      setRemaining((value) => {
        if (value <= 1) {
          clearInterval(timer)
          return 0
        }
        return value - 1
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [detail, index, round, done])

  async function start(practiceId: string) {
    setError('')
    try {
      const data = await api.get<PracticeDetail>(`/practices/${practiceId}`)
      setDetail(data)
      setIndex(0)
      setRound(0)
      setDone(false)
      setRemaining(data.steps[0]?.seconds ?? 0)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  function exit() {
    Modal.confirm({
      title: '确认退出练习?',
      content: '中途退出不会保存练习记录,随时可以重新开始。',
      okText: '退出',
      cancelText: '继续练习',
      onOk: () => {
        setDetail(null)
        setDone(false)
      },
    })
  }

  function next() {
    if (!detail) return
    if (index + 1 < detail.steps.length) {
      setIndex(index + 1)
      return
    }
    const rounds = Math.max(1, detail.repeat || 1)
    if (round + 1 < rounds) {
      setRound(round + 1)
      setIndex(0)
      return
    }
    setDone(true)
  }

  if (!detail) {
    return (
      <div className="page-stack">
        <div>
          <Typography.Title level={4} style={{ marginBottom: 4 }}>
            放松练习
          </Typography.Title>
          <Typography.Text type="secondary">
            跟随提示逐步完成,任何不舒服都可以立即停止。
          </Typography.Text>
        </div>
        {error && <Alert type="error" showIcon message={error} />}
        <div className="scale-grid">
          {practices.map((practice) => (
            <Card key={practice.id} title={practice.name}>
              <Space direction="vertical" size="small" style={{ width: '100%' }}>
                <Typography.Text type="secondary">{practice.summary}</Typography.Text>
                <Space>
                  <Tag>{practice.duration_seconds} 秒</Tag>
                  <Tag>重复 {practice.repeat} 轮</Tag>
                </Space>
                <Button type="primary" onClick={() => void start(practice.id)}>
                  开始练习
                </Button>
              </Space>
            </Card>
          ))}
        </div>
      </div>
    )
  }

  if (done) {
    return (
      <div className="page-stack">
        <Card>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Typography.Title level={4} style={{ margin: 0 }}>
              「{detail.name}」已完成
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
              {detail.stop_hint}
            </Typography.Paragraph>
            <Button type="primary" onClick={() => setDetail(null)}>
              返回练习列表
            </Button>
          </Space>
        </Card>
      </div>
    )
  }

  const step = detail.steps[index]
  const rounds = Math.max(1, detail.repeat || 1)
  return (
    <div className="page-stack">
      <Card>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {detail.name}
            </Typography.Title>
            <Typography.Text type="secondary">
              第 {round + 1}/{rounds} 轮 · 第 {index + 1}/{detail.steps.length} 步
            </Typography.Text>
          </Space>
          <Progress
            percent={Math.round(
              ((round * detail.steps.length + index) / (rounds * detail.steps.length)) * 100
            )}
            showInfo={false}
          />
          <Typography.Paragraph className="pre-wrap" style={{ margin: 0 }}>
            {step?.instruction}
          </Typography.Paragraph>
          <Typography.Title level={3} style={{ margin: 0, color: '#3d7f74' }}>
            {remaining > 0 ? `剩余 ${remaining} 秒` : '这一步可以结束了'}
          </Typography.Title>
          <Space>
            <Button type="primary" disabled={remaining > 0} onClick={next}>
              {index + 1 === detail.steps.length && round + 1 === rounds ? '完成' : '下一步'}
            </Button>
            {remaining > 0 && (
              <Button onClick={() => setRemaining(0)}>跳过计时</Button>
            )}
            <Button danger onClick={exit}>
              停止练习
            </Button>
          </Space>
        </Space>
      </Card>
    </div>
  )
}
