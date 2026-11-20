import { Alert, Button, Card, Progress, Radio, Space, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'

import { api, errorMessage } from '../api'
import { CrisisCard } from '../components/CrisisCard'
import type { AssessmentOutcome, ScaleDetail, ScaleSummary } from '../types'

export function AssessmentPage() {
  const [scales, setScales] = useState<ScaleSummary[]>([])
  const [detail, setDetail] = useState<ScaleDetail | null>(null)
  const [index, setIndex] = useState(0)
  const [answers, setAnswers] = useState<number[]>([])
  const [outcome, setOutcome] = useState<AssessmentOutcome | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api
      .get<{ items: ScaleSummary[] }>('/scales')
      .then((data) => setScales(data.items))
      .catch((err) => setError(errorMessage(err)))
  }, [])

  async function start(scaleId: string) {
    setError('')
    setOutcome(null)
    try {
      const data = await api.get<ScaleDetail>(`/scales/${scaleId}`)
      setDetail(data)
      setIndex(0)
      setAnswers([])
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  function reset() {
    setDetail(null)
    setOutcome(null)
    setIndex(0)
    setAnswers([])
  }

  async function submit(finalAnswers: number[]) {
    if (!detail) return
    setLoading(true)
    setError('')
    try {
      const data = await api.post<AssessmentOutcome>(`/scales/${detail.id}/submit`, {
        answers: finalAnswers,
      })
      setOutcome(data)
      setDetail(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  function choose(value: number) {
    if (!detail) return
    const next = [...answers]
    next[index] = value
    setAnswers(next)
    if (index + 1 >= detail.items.length) {
      void submit(next)
    } else {
      setIndex(index + 1)
    }
  }

  if (outcome) {
    return (
      <div className="page-stack">
        <Card>
          <div className="result-block">
            <Typography.Title level={4} style={{ margin: 0 }}>
              评估结果
            </Typography.Title>
            <Space wrap>
              <Tag color="blue">
                总分 {outcome.total}/{outcome.max_total}
              </Tag>
              <Tag color={outcome.high_risk ? 'red' : 'green'}>
                分级: {outcome.label}
              </Tag>
            </Space>
            <Typography.Paragraph className="pre-wrap" style={{ margin: 0 }}>
              {outcome.text}
            </Typography.Paragraph>
            {outcome.high_risk && (
              <Alert
                type="warning"
                showIcon
                message={
                  outcome.notified
                    ? '已向你的紧急联系人发送通知。'
                    : '未开启紧急联系人通知。如需自动通知,可前往设置联系人。'
                }
              />
            )}
          </div>
        </Card>
        {outcome.high_risk && <CrisisCard />}
        <Space>
          <Button onClick={() => void start(outcome.scale)}>再测一次</Button>
          <Button type="primary" onClick={reset}>
            返回量表列表
          </Button>
        </Space>
      </div>
    )
  }

  if (detail) {
    const current = detail.items[index]
    const progress = Math.round((index / detail.items.length) * 100)
    return (
      <div className="page-stack">
        <Card>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Space style={{ width: '100%', justifyContent: 'space-between' }}>
              <Typography.Title level={4} style={{ margin: 0 }}>
                {detail.name}
              </Typography.Title>
              <Typography.Text type="secondary">
                第 {index + 1}/{detail.items.length} 题
              </Typography.Text>
            </Space>
            <Progress percent={progress} showInfo={false} />
            <Typography.Text type="secondary">{detail.intro}</Typography.Text>
            <Typography.Title level={5} style={{ margin: 0 }}>
              {current}
            </Typography.Title>
            <Radio.Group
              key={`${detail.id}-${index}`}
              value={answers[index]}
              onChange={(event) => choose(Number(event.target.value))}
            >
              <Space direction="vertical">
                {detail.options.map((option) => (
                  <Radio key={option.value} value={option.value}>
                    {option.label}
                  </Radio>
                ))}
              </Space>
            </Radio.Group>
            {error && <Alert type="error" showIcon message={error} />}
            <Space>
              <Button disabled={index === 0} onClick={() => setIndex(index - 1)}>
                上一题
              </Button>
              <Button onClick={reset}>退出评估</Button>
            </Space>
          </Space>
        </Card>
      </div>
    )
  }

  return (
    <div className="page-stack">
      <div>
        <Typography.Title level={4} style={{ marginBottom: 4 }}>
          量表评估
        </Typography.Title>
        <Typography.Text type="secondary">
          所有分数由本地确定性计算,结果是筛查提示,不是诊断。
        </Typography.Text>
      </div>
      {error && <Alert type="error" showIcon message={error} />}
      <div className="scale-grid">
        {scales.map((scale) => (
          <Card key={scale.id} title={scale.name}>
            <Space direction="vertical" size="small" style={{ width: '100%' }}>
              <Typography.Text type="secondary">
                {scale.available ? `${scale.item_count} 题` : '题目文本待授权确认'}
              </Typography.Text>
              {scale.available ? (
                <Button type="primary" onClick={() => void start(scale.id)}>
                  开始评估
                </Button>
              ) : (
                <Button disabled>暂不可用</Button>
              )}
            </Space>
          </Card>
        ))}
      </div>
      {loading && <Typography.Text type="secondary">正在计算…</Typography.Text>}
    </div>
  )
}
