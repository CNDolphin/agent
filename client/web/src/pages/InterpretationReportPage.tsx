import { Alert, Button, Space, Spin, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { ApiError, api, errorMessage } from '../api'
import '../mi-report.css'
import { useStatus } from '../status'
import type { InterpretationReport } from '../types'
import { REPORTS_UPDATED_EVENT } from './ReportsPage'

export function InterpretationReportPage() {
  const { profileId } = useParams<{ profileId: string }>()
  const { status } = useStatus()
  const navigate = useNavigate()
  const profile = status?.profiles.find((item) => item.id === profileId)

  const [report, setReport] = useState<InterpretationReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<{ code: string; message: string } | null>(null)

  const load = useCallback(
    async (refresh = false) => {
      if (!profileId) return
      setLoading(true)
      setError(null)
      try {
        const query = refresh ? '?refresh=1' : ''
        const data = await api.get<InterpretationReport>(
          `/profiles/${profileId}/interpretation-report${query}`,
        )
        setReport(data)
      } catch (err) {
        setReport(null)
        if (err instanceof ApiError && err.code === 'onboarding_required') {
          setError({ code: err.code, message: err.message })
        } else {
          setError({ code: 'error', message: errorMessage(err) })
        }
      } finally {
        setLoading(false)
      }
    },
    [profileId],
  )

  useEffect(() => {
    void load()
  }, [load])

  // 会话内提交报告并修正解读后，自动刷新当前报告。
  useEffect(() => {
    const handler = () => void load()
    window.addEventListener(REPORTS_UPDATED_EVENT, handler)
    return () => window.removeEventListener(REPORTS_UPDATED_EVENT, handler)
  }, [load])

  if (!profile) {
    return (
      <div className="page-stack">
        <Alert
          type="warning"
          showIcon
          message="档案不存在或已被删除"
          action={
            <Button size="small" onClick={() => navigate('/profiles')}>
              返回用户管理
            </Button>
          }
        />
      </div>
    )
  }

  return (
    <div className="page-stack">
      <div className="page-head">
        <Space direction="vertical" size={0}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            多元智能解读报告
          </Typography.Title>
          <Typography.Text type="secondary">
            {profile.nickname} · {profile.role === 'main' ? '主账号' : '子账号'} ·
            基于该成员的基础测评与已上传基因报告生成
          </Typography.Text>
        </Space>
        <Space className="mi-report-no-print">
          <Button onClick={() => navigate('/profiles')}>返回用户管理</Button>
          <Button type="primary" loading={loading} onClick={() => void load(true)}>
            生成报告
          </Button>
          <Button disabled={!report} onClick={() => window.print()}>
            打印 / 导出 PDF
          </Button>
        </Space>
      </div>

      {error && error.code === 'onboarding_required' ? (
        <Alert
          type="warning"
          showIcon
          message="该成员尚未完成基础测评"
          description={
            <Space direction="vertical" size={6}>
              <span>{error.message}。请切换到该成员后完成基础测评，再查看解读报告。</span>
              <Button size="small" onClick={() => navigate('/onboarding')}>
                去完成基础测评
              </Button>
            </Space>
          }
        />
      ) : null}
      {error && error.code !== 'onboarding_required' ? (
        <Alert type="error" showIcon message={error.message} />
      ) : null}

      {loading ? (
        <div className="center-page">
          <Spin size="large" tip="正在生成解读报告…">
            <div className="spin-holder" />
          </Spin>
        </div>
      ) : null}

      {!loading && report && report.source?.kind === 'report' ? (
        <Alert
          className="mi-report-no-print"
          type="info"
          showIcon
          message={`数据来源：会话提交报告《${report.source.title || '提交报告'}》`}
          description={
            <Space direction="vertical" size={2}>
              <span>
                报告分数已覆盖基础测评（智能 {report.source.coverage?.intel ?? 0}/8、指标{' '}
                {report.source.coverage?.ind ?? 0}/40），自评问卷与基因融合不再参与。
              </span>
              <span>
                {report.source.filename || '未记录文件名'}
                {report.source.uploaded_at
                  ? ` · 提交于 ${report.source.uploaded_at.replace('T', ' ').slice(0, 19)}`
                  : ''}
              </span>
            </Space>
          }
        />
      ) : null}

      {!loading && report ? (
        <div className="mi-report" dangerouslySetInnerHTML={{ __html: report.html }} />
      ) : null}
    </div>
  )
}
