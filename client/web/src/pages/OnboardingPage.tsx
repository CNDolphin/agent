import {
  Alert,
  Button,
  Card,
  Progress,
  Radio,
  Space,
  Steps,
  Tag,
  Typography,
} from 'antd'
import { useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, errorMessage } from '../api'
import type {
  OnboardingGene,
  OnboardingQuestionnaire,
  OnboardingResult,
  OnboardingState,
} from '../types'

const CONFIDENCE_LABEL: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
}

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const text = String(reader.result ?? '')
      resolve(text.includes(',') ? text.slice(text.indexOf(',') + 1) : text)
    }
    reader.onerror = () => reject(new Error('读取文件失败，请重试'))
    reader.readAsDataURL(file)
  })
}

function OrderList({
  items,
  labels,
  onChange,
}: {
  items: string[]
  labels: Record<string, string>
  onChange: (next: string[]) => void
}) {
  function move(index: number, delta: number) {
    const target = index + delta
    if (target < 0 || target >= items.length) return
    const next = [...items]
    ;[next[index], next[target]] = [next[target], next[index]]
    onChange(next)
  }
  return (
    <div className="mi-order-list">
      {items.map((id, index) => (
        <div className="mi-order-row" key={id}>
          <span className="mi-order-rank">{index + 1}</span>
          <span className="mi-order-label">{labels[id] ?? id}</span>
          <Space size={4}>
            <Button
              size="small"
              disabled={index === 0}
              aria-label={`上移 ${labels[id] ?? id}`}
              onClick={() => move(index, -1)}
            >
              上移
            </Button>
            <Button
              size="small"
              disabled={index === items.length - 1}
              aria-label={`下移 ${labels[id] ?? id}`}
              onClick={() => move(index, 1)}
            >
              下移
            </Button>
          </Space>
        </div>
      ))}
    </div>
  )
}

function ScoreSummary({ result }: { result: OnboardingResult }) {
  const rows = useMemo(
    () => Object.values(result.intel).sort((a, b) => b.score - a.score),
    [result],
  )
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Typography.Title level={4} style={{ margin: 0 }}>
        你的基础测评结果
      </Typography.Title>
      <Typography.Text type="secondary">
        融合口径 {result.fusion_version}
        {result.gene_used ? '，已参考基因检测报告' : '，仅基于问卷与排序'}。
        这是一份近似画像，不是诊断。
      </Typography.Text>
      {rows.map((item) => (
        <div key={item.id} className="mi-score-row">
          <span className="mi-score-name">
            {item.name}
            <Tag style={{ marginLeft: 8 }}>第 {item.rank} 位</Tag>
          </span>
          <Progress percent={item.score} size="small" />
        </div>
      ))}
      <Alert
        type="info"
        showIcon
        message="已整理为长期记忆"
        description="之后的对话会自动参考这份基础测评，不需要每次重复说明。"
      />
    </Space>
  )
}

export function OnboardingPage() {
  const navigate = useNavigate()
  const [bank, setBank] = useState<OnboardingQuestionnaire | null>(null)
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [intelOrder, setIntelOrder] = useState<string[]>([])
  const [indOrder, setIndOrder] = useState<Record<string, string[]>>({})
  const [result, setResult] = useState<OnboardingResult | null>(null)
  const [gene, setGene] = useState<OnboardingGene | null>(null)
  const [step, setStep] = useState(0)
  const [qIndex, setQIndex] = useState(0)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement | null>(null)
  const rankTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const advanceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [questionnaire, current] = await Promise.all([
          api.get<OnboardingQuestionnaire>('/onboarding/questionnaire'),
          api.get<OnboardingState>('/onboarding'),
        ])
        if (cancelled) return
        setBank(questionnaire)
        setAnswers(current.answers ?? {})
        setGene(current.gene ?? null)
        setResult(current.result ?? null)
        setIntelOrder(
          current.rankings?.intel?.length
            ? current.rankings.intel
            : questionnaire.intelligences.map((item) => item.id),
        )
        setIndOrder(
          Object.fromEntries(
            questionnaire.intelligences.map((item) => [
              item.id,
              current.rankings?.ind?.[item.id]?.length
                ? current.rankings.ind[item.id]
                : item.indicators.map((ind) => ind.id),
            ]),
          ),
        )
        if (current.status === 'completed') setStep(3)

        // 从第一道未作答的题目继续
        const restored = current.answers ?? {}
        let start = questionnaire.questions.length
        for (let index = 0; index < questionnaire.questions.length; index += 1) {
          const question = questionnaire.questions[index]
          if (restored[String(question.id)] === undefined) {
            start = index
            break
          }
        }
        setQIndex(start)
      } catch (err) {
        if (!cancelled) setError(errorMessage(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(
    () => () => {
      if (advanceTimer.current) clearTimeout(advanceTimer.current)
    },
    [],
  )

  const doneItems = useMemo(() => {
    if (!bank) return 0
    let count = 0
    bank.intelligences.forEach((intel) => {
      intel.indicators.forEach((ind) => {
        const positive = bank.questions.find(
          (item) => item.indicator === ind.id && !item.reverse,
        )
        const value = positive ? answers[String(positive.id)] : undefined
        if (!positive || value === undefined) return
        if (value !== 3) {
          count += 1
          return
        }
        if (answers[String(positive.id + 1)] !== undefined) count += 1
      })
    })
    return count
  }, [answers, bank])

  function choose(questionId: number, value: number) {
    const nextAnswers = { ...answers, [String(questionId)]: value }
    setAnswers(nextAnswers)
    api
      .put<OnboardingState>('/onboarding/answers', {
        answers: { [String(questionId)]: value },
      })
      .catch(() => undefined)

    const currentIndex = (bank?.questions ?? []).findIndex(
      (item) => item.id === questionId,
    )
    if (currentIndex < 0) return
    if (advanceTimer.current) clearTimeout(advanceTimer.current)
    advanceTimer.current = setTimeout(
      () => setQIndex(currentIndex + 1),
      260,
    )
  }

  function goPrev() {
    if (advanceTimer.current) clearTimeout(advanceTimer.current)
    setQIndex(Math.max(qIndex - 1, 0))
  }

  function goToRanking() {
    if (advanceTimer.current) clearTimeout(advanceTimer.current)
    setStep(1)
  }

  function persistRankings(nextIntel: string[], nextInd: Record<string, string[]>) {
    if (rankTimer.current) clearTimeout(rankTimer.current)
    rankTimer.current = setTimeout(() => {
      api
        .put<OnboardingState>('/onboarding/rankings', {
          intel: nextIntel,
          ind: nextInd,
        })
        .catch(() => undefined)
    }, 400)
  }

  function changeIntel(next: string[]) {
    setIntelOrder(next)
    persistRankings(next, indOrder)
  }

  function changeInd(intelId: string, next: string[]) {
    const merged = { ...indOrder, [intelId]: next }
    setIndOrder(merged)
    persistRankings(intelOrder, merged)
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    if (!busy) setDragging(true)
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    const next = event.relatedTarget as Node | null
    if (next && event.currentTarget.contains(next)) return
    setDragging(false)
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    if (busy) return
    const file = event.dataTransfer.files?.[0]
    if (file) void uploadGene(file)
  }

  async function uploadGene(file: File) {
    setError('')
    const suffix = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
    if (!['.pdf', '.docx', '.txt'].includes(suffix)) {
      setError('只支持 PDF、DOCX、TXT 格式的基因检测报告')
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      setError('文件超过 10MB 上限')
      return
    }
    setBusy(true)
    try {
      const content = await readBase64(file)
      const data = await api.post<{ gene: OnboardingGene }>('/onboarding/gene', {
        filename: file.name,
        content,
      })
      setGene(data.gene)
    } catch (err) {
      setError(
        `${errorMessage(err)}。可以换一份文件重试，或直接跳过这一步。`,
      )
    } finally {
      setBusy(false)
    }
  }

  async function removeGene() {
    setBusy(true)
    try {
      const data = await api.delete<OnboardingState>('/onboarding/gene')
      setGene(data.gene)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function complete() {
    setBusy(true)
    setError('')
    try {
      // 排序保存有 400ms 防抖；完成前先落库，避免未手动调整或刚调整完时提交空排序
      if (rankTimer.current) {
        clearTimeout(rankTimer.current)
        rankTimer.current = null
      }
      await api.put<OnboardingState>('/onboarding/rankings', {
        intel: intelOrder,
        ind: indOrder,
      })
      const data = await api.post<{ result: OnboardingResult; memory_text: string }>(
        '/onboarding/complete',
      )
      setResult(data.result)
      setStep(3)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="center-page">
        <Typography.Text type="secondary">正在读取测评数据…</Typography.Text>
      </div>
    )
  }

  if (!bank) {
    return (
      <div className="onboarding-page">
        <Alert type="error" showIcon message={error || '题库加载失败'} />
      </div>
    )
  }

  const intelLabels = Object.fromEntries(
    bank.intelligences.map((item) => [item.id, item.name]),
  )
  const questions = bank.questions
  const currentQuestion = qIndex < questions.length ? questions[qIndex] : undefined
  const currentIntel = currentQuestion
    ? bank.intelligences.find((item) => item.id === currentQuestion.intelligence)
    : undefined

  return (
    <div className="onboarding-page">
      <div className="onboarding-head">
        <Typography.Title level={3} style={{ margin: 0 }}>
          入学测评
        </Typography.Title>
        <Typography.Text type="secondary">
          完成一次 80 题问卷、两组排序，可选上传基因检测报告。结果只保存在本机，
          并整理成后续对话的基础记忆。
        </Typography.Text>
      </div>

      <Steps
        current={Math.min(step, 2)}
        size="small"
        items={[
          { title: '问卷测评', description: `${doneItems}/40 项` },
          { title: '主观排序', description: '智能与指标' },
          { title: '基因报告（可选）', description: gene ? '已上传' : '可跳过' },
        ]}
      />

      {error && <Alert type="error" showIcon message={error} />}

      {step === 0 &&
        (currentQuestion ? (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Typography.Text type="secondary">
              每次只答一题，选择后自动进入下一题；每项指标由一道正向题和一道反向题组成，
              两题都会依次出现，请按当前真实情况独立作答，可用「上一题」回改。
            </Typography.Text>
            <Card size="small" className="mi-single">
              <div className="mi-single-top">
                <Tag>{currentIntel?.name ?? '问卷'}</Tag>
                <Typography.Text type="secondary">
                  第 {currentQuestion.id} 题 / 共 {questions.length} 题
                </Typography.Text>
              </div>
              <Progress
                percent={Math.round((doneItems / 40) * 100)}
                size="small"
                showInfo={false}
              />
              <div className="mi-single-text">
                {currentQuestion.id}. {currentQuestion.text}
              </div>
              {currentQuestion.reverse && (
                <Typography.Text type="secondary" className="mi-single-note">
                  本题与该指标的正向题配对，测的是同一个方面，请按真实情况独立作答。
                </Typography.Text>
              )}
              <Radio.Group
                className="mi-single-options"
                aria-label={`题目 ${currentQuestion.id}`}
                value={answers[String(currentQuestion.id)]}
                onChange={(event) =>
                  choose(currentQuestion.id, Number(event.target.value))
                }
              >
                {bank.scale.labels.map((label, index) => (
                  <Radio key={label} value={index + 1}>
                    {label}
                  </Radio>
                ))}
              </Radio.Group>
            </Card>
            <div className="onboarding-actions">
              <Typography.Text type="secondary">{doneItems}/40 项已完成</Typography.Text>
              <Space>
                <Button disabled={qIndex === 0} onClick={goPrev}>
                  上一题
                </Button>
                <Button type="primary" disabled={doneItems < 10} onClick={goToRanking}>
                  下一步：排序
                </Button>
              </Space>
            </div>
          </Space>
        ) : (
          <Card size="small" title="问卷已答完">
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Typography.Text>
                共完成 {doneItems}/40 项能力指标，答案已保存在本机。
              </Typography.Text>
              {doneItems < 10 && (
                <Typography.Text type="warning">
                  至少完成 10 项才能继续，可以返回补答。
                </Typography.Text>
              )}
              <Space>
                <Button onClick={() => setQIndex(questions.length - 1)}>
                  返回上一题
                </Button>
                <Button type="primary" disabled={doneItems < 10} onClick={goToRanking}>
                  进入排序
                </Button>
              </Space>
            </Space>
          </Card>
        ))}

      {step === 1 && (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Card size="small" title="八大智能排序（从最强到最弱）">
            <OrderList
              items={intelOrder}
              labels={intelLabels}
              onChange={changeIntel}
            />
          </Card>
          {bank.intelligences.map((intel) => (
            <Card key={intel.id} size="small" title={`${intel.name}：组内 5 项指标排序`}>
              <OrderList
                items={indOrder[intel.id] ?? []}
                labels={Object.fromEntries(
                  intel.indicators.map((ind) => [ind.id, `${ind.name}（${ind.definition}）`]),
                )}
                onChange={(next) => changeInd(intel.id, next)}
              />
            </Card>
          ))}
          <div className="onboarding-actions">
            <Button onClick={() => setStep(0)}>上一步</Button>
            <Button type="primary" onClick={() => setStep(2)}>
              下一步：基因报告
            </Button>
          </div>
        </Space>
      )}

      {step === 2 && (
        <div
          className={dragging ? 'mi-drop-page mi-drop-page-active' : 'mi-drop-page'}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Card size="small" title="上传基因检测报告（可选）">
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Typography.Text type="secondary">
                  支持 PDF / DOCX / TXT，大小不超过 10MB。点击选择，或直接把文件拖到本页上传。
                  上传后由 AI 抽取 8 项智能分，与问卷、排序一起融合；不上传也能完成测评。
                  原文只保存在本机。
                </Typography.Text>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".pdf,.docx,.txt"
                  style={{ display: 'none' }}
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) void uploadGene(file)
                    event.target.value = ''
                  }}
                />
                <Space>
                  <Button loading={busy} onClick={() => fileRef.current?.click()}>
                    选择基因报告
                  </Button>
                  {gene && (
                    <Button danger onClick={() => void removeGene()}>
                      移除
                    </Button>
                  )}
                </Space>
                {dragging && (
                  <Typography.Text type="success">松开鼠标即可上传</Typography.Text>
                )}
                {gene && (
                  <div className="mi-gene">
                    <Typography.Text strong>{gene.filename}</Typography.Text>
                    <Tag color="geekblue">
                      识别置信度：{CONFIDENCE_LABEL[gene.confidence] ?? gene.confidence}
                    </Tag>
                    <div className="mi-gene-scores">
                      {bank.intelligences.map((intel) => (
                        <span key={intel.id}>
                          {intel.name} {gene.scores[intel.id] ?? '—'}
                        </span>
                      ))}
                    </div>
                    {gene.notes && (
                      <Typography.Text type="secondary">
                        提取依据：{gene.notes}
                      </Typography.Text>
                    )}
                  </div>
                )}
              </Space>
            </Card>
            <div className="onboarding-actions">
              <Button onClick={() => setStep(1)}>上一步</Button>
              <Button type="primary" onClick={() => void complete()} loading={busy}>
                {gene ? '完成测评' : '跳过基因报告，完成测评'}
              </Button>
            </div>
          </Space>
        </div>
      )}

      {step === 3 && result && (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <ScoreSummary result={result} />
          <div className="onboarding-actions">
            <Button type="primary" onClick={() => navigate('/')}>
              进入对话
            </Button>
          </div>
        </Space>
      )}
    </div>
  )
}
