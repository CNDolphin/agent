import { Alert, Button, Card, Checkbox, Space, Tag, Typography } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, errorMessage } from '../api'
import { useStatus } from '../status'
import type { ConsentInfo } from '../types'

export function ConsentPage() {
  const { refresh } = useStatus()
  const navigate = useNavigate()
  const [consent, setConsent] = useState<ConsentInfo | null>(null)
  const [checked, setChecked] = useState(false)
  const [readToEnd, setReadToEnd] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const scrollerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    api
      .get<ConsentInfo>('/consents/latest')
      .then((data) => {
        setConsent(data)
        setChecked(data.agreed)
        setReadToEnd(data.agreed)
      })
      .catch((err) => setError(errorMessage(err)))
  }, [])

  useEffect(() => {
    const element = scrollerRef.current
    if (element && element.scrollHeight <= element.clientHeight + 4) {
      setReadToEnd(true)
    }
  }, [consent])

  function onScroll() {
    const element = scrollerRef.current
    if (!element) return
    if (element.scrollTop + element.clientHeight >= element.scrollHeight - 8) {
      setReadToEnd(true)
    }
  }

  async function agree() {
    if (!consent) return
    setLoading(true)
    setError('')
    try {
      await api.post('/consents/agree', { version: consent.latest.version })
      await refresh()
      navigate('/contact', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  if (!consent) {
    return (
      <div className="center-page">
        <Card className="narrow-card">
          {error ? <Alert type="error" showIcon message={error} /> : <Typography.Text>正在加载说明…</Typography.Text>}
        </Card>
      </div>
    )
  }

  if (consent.agreed) {
    return (
      <div className="center-page">
        <Card className="narrow-card">
          <Typography.Title level={3}>已同意使用说明</Typography.Title>
          <Alert
            type="success"
            showIcon
            message={`已同意版本 ${consent.agreed_version}`}
          />
          <Button
            type="primary"
            block
            className="page-action"
            onClick={() => navigate('/', { replace: true })}
          >
            继续使用
          </Button>
        </Card>
      </div>
    )
  }

  return (
    <div className="center-page">
      <Card className="consent-card">
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div>
            <Typography.Title level={3} style={{ marginBottom: 4 }}>
              使用说明与知情同意
            </Typography.Title>
            <Tag>版本 {consent.latest.version}</Tag>
          </div>
          <div className="scale-text" ref={scrollerRef} onScroll={onScroll}>
            {consent.latest.text}
          </div>
          {!readToEnd && <Typography.Text type="secondary">请阅读到说明末尾后再勾选同意。</Typography.Text>}
          <Checkbox
            checked={checked}
            disabled={!readToEnd}
            onChange={(event) => setChecked(event.target.checked)}
          >
            我已阅读并理解上述说明
          </Checkbox>
          {error && <Alert type="error" showIcon message={error} />}
          <Button
            type="primary"
            block
            disabled={!checked || !readToEnd}
            loading={loading}
            onClick={() => void agree()}
          >
            同意并继续
          </Button>
        </Space>
      </Card>
    </div>
  )
}
