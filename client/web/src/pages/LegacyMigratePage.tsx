import { Alert, Button, Card, Input, Space, Typography } from 'antd'
import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'

import { api, errorMessage } from '../api'
import { useStatus } from '../status'

export function LegacyMigratePage() {
  const { status, refresh } = useStatus()
  const navigate = useNavigate()
  const [passphrase, setPassphrase] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  if (status === null) {
    return (
      <div className="center-page">
        <Card className="narrow-card">
          <Typography.Text>正在读取本地数据…</Typography.Text>
        </Card>
      </div>
    )
  }
  if (!status.legacy_required) {
    return <Navigate to={status.logged_in ? '/' : '/login'} replace />
  }
  if (status.device_mode === 'lan') {
    return (
      <div className="center-page">
        <Card className="narrow-card">
          <Typography.Title level={3}>旧版数据待升级</Typography.Title>
          <Typography.Paragraph type="secondary">
            这台电脑上的本地数据仍使用旧版口令加密,需要在桌面端完成一次性升级后,
            子账号才能通过局域网访问。
          </Typography.Paragraph>
        </Card>
      </div>
    )
  }

  async function migrate() {
    if (!passphrase.trim()) {
      setError('请输入旧版本地口令')
      return
    }
    setLoading(true)
    setError('')
    try {
      await api.post('/legacy/migrate', { passphrase })
      await refresh()
      navigate('/login', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="center-page">
      <Card className="narrow-card">
        <Typography.Title level={3}>升级旧版本地数据</Typography.Title>
        <Typography.Paragraph type="secondary">
          检测到旧版使用口令加密的本地数据。输入原口令完成一次性升级,
          之后改用设备密钥自动加密,日常只需手机号 + 密码登录。升级失败不会修改原数据。
        </Typography.Paragraph>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Input.Password
            aria-label="旧口令"
            placeholder="请输入旧版本地口令"
            value={passphrase}
            autoFocus
            onChange={(event) => setPassphrase(event.target.value)}
            onPressEnter={() => void migrate()}
          />
          {error && <Alert type="error" showIcon message={error} />}
          <Button type="primary" block loading={loading} onClick={() => void migrate()}>
            升级并继续
          </Button>
        </Space>
      </Card>
    </div>
  )
}
