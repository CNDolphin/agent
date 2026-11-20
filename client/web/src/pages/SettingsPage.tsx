import { Alert, Button, Card, Descriptions, Space, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, clearDeviceToken, errorMessage } from '../api'
import { useStatus } from '../status'

interface ContentUpdate {
  id: number
  kind: string
  version: string
  size_bytes?: number
  notes?: string
  forced?: boolean
}

interface UpdateStatus {
  app_version: string
  platform: string
  applied: Record<string, string>
  available: ContentUpdate[]
}

interface UpdateResult {
  kind: string
  version: string
  path: string
  restart_required: boolean
  manual: boolean
}

const KIND_LABELS: Record<string, string> = {
  skills: '技能包',
  quiz: '题库',
  rules: '风险规则',
  scales: '量表',
  app: '客户端程序',
}

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind
}

function formatSize(bytes?: number): string {
  if (!bytes || bytes <= 0) return ''
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function SettingsPage() {
  const { status, refresh } = useStatus()
  const navigate = useNavigate()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [updates, setUpdates] = useState<UpdateStatus | null>(null)
  const [checking, setChecking] = useState(false)
  const [updatingId, setUpdatingId] = useState<number | null>(null)
  const [notice, setNotice] = useState('')

  const desktop = status?.device_mode === 'desktop'
  const profile = status?.active_profile

  useEffect(() => {
    if (!desktop) return
    let alive = true
    api
      .get<UpdateStatus>('/updates')
      .then((data) => {
        if (alive) setUpdates(data)
      })
      .catch(() => {
        // 更新服务未就绪时不影响设置页其他功能。
      })
    return () => {
      alive = false
    }
  }, [desktop])

  async function checkUpdates() {
    setChecking(true)
    setError('')
    setNotice('')
    try {
      setUpdates(await api.post<UpdateStatus>('/updates/check'))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setChecking(false)
    }
  }

  async function applyUpdate(item: ContentUpdate) {
    setUpdatingId(item.id)
    setError('')
    setNotice('')
    try {
      const result = await api.post<UpdateResult>(`/updates/${item.id}/download`)
      setUpdates(await api.get<UpdateStatus>('/updates'))
      if (result.manual) {
        setNotice(
          `客户端程序包 ${result.version} 已下载到 ${result.path},请退出应用后手动安装。`,
        )
      } else if (result.restart_required) {
        setNotice(`${kindLabel(result.kind)} 已更新到 ${result.version},重启应用后生效。`)
      } else {
        setNotice(`${kindLabel(result.kind)} 已更新到 ${result.version},已立即生效。`)
      }
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setUpdatingId(null)
    }
  }

  async function logout() {
    setLoading(true)
    setError('')
    try {
      if (desktop) {
        await api.post('/auth/logout')
      } else {
        // 局域网设备只清理本机设备令牌,主账号登录态保持不变。
        clearDeviceToken()
      }
      await refresh()
      navigate('/login', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page-stack">
      <Typography.Title level={4} style={{ marginBottom: 0 }}>
        设置
      </Typography.Title>
      {error && <Alert type="error" showIcon message={error} />}

      <Card title="账号与隐私">
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="访问方式">
            {desktop ? '桌面端(管理员)' : '局域网设备'}
          </Descriptions.Item>
          <Descriptions.Item label="当前档案">
            {profile ? (
              <Space>
                <Tag color={profile.role === 'main' ? 'blue' : 'default'}>
                  {profile.role === 'main' ? '主账号' : '子账号'}
                </Tag>
                {profile.nickname}
              </Space>
            ) : (
              '未登录'
            )}
          </Descriptions.Item>
          {desktop && (
            <Descriptions.Item label="主账号手机号">
              {status?.phone_mask ?? '未登录'}
            </Descriptions.Item>
          )}
          {!desktop && profile && (
            <Descriptions.Item label="登录账号">{profile.username}</Descriptions.Item>
          )}
          <Descriptions.Item label="已同意说明版本">
            {status?.consent_version ?? '未同意'}
          </Descriptions.Item>
          <Descriptions.Item label="紧急联系人">
            {status?.emergency_authorized ? '已授权高风险通知' : '未授权'}
          </Descriptions.Item>
          <Descriptions.Item label="数据存储">
            <Space>
              <Tag color="green">本机加密</Tag>
              <Typography.Text type="secondary">
                本地库由设备密钥自动加密,无需再输入本地口令
              </Typography.Text>
            </Space>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {desktop && (
        <Card title="本地账号">
          <Space direction="vertical" size="small">
            <Typography.Text type="secondary">
              在「用户管理」中创建子账号,并用用户名 + 密码让手机或其他电脑登录。
              所有子账号共用主账号积分,会话与资料按档案独立保存。
            </Typography.Text>
            <Space wrap>
              <Button onClick={() => navigate('/profiles')}>用户管理</Button>
              <Button onClick={() => navigate('/onboarding')}>基础测评</Button>
            </Space>
          </Space>
        </Card>
      )}

      {status?.lan_enabled && (
        <Card title="局域网访问">
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            局域网访问已开启,手机/平板可在浏览器中使用子账号登录桌面端服务。
            当前为明文 HTTP,请仅在可信网络内使用,不要做公网端口映射。
            {desktop && ' 局域网地址会在启动日志中打印。'}
          </Typography.Paragraph>
        </Card>
      )}

      <Card title="紧急联系人">
        <Space direction="vertical" size="small">
          <Typography.Text type="secondary">
            单独开启授权后,高风险时会发送一条通知;可随时关闭。联系人按当前档案独立保存。
          </Typography.Text>
          <Button onClick={() => navigate('/contact')}>管理紧急联系人</Button>
        </Space>
      </Card>

      {desktop && (
        <Card
          title="版本与更新"
          extra={
            <Button size="small" loading={checking} onClick={() => void checkUpdates()}>
              检查更新
            </Button>
          }
        >
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="客户端版本">
              <Space>
                <Tag>v{updates?.app_version ?? '—'}</Tag>
                {updates && (
                  <Typography.Text type="secondary">平台 {updates.platform}</Typography.Text>
                )}
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="已应用内容">
              {updates && Object.keys(updates.applied).length > 0 ? (
                <Space wrap size={[8, 8]}>
                  {Object.entries(updates.applied).map(([kind, version]) => (
                    <Tag key={kind}>{`${kindLabel(kind)} v${version}`}</Tag>
                  ))}
                </Space>
              ) : (
                <Typography.Text type="secondary">尚未应用在线内容</Typography.Text>
              )}
            </Descriptions.Item>
          </Descriptions>

          {notice && (
            <Alert style={{ marginTop: 12 }} type="success" showIcon message={notice} />
          )}

          {updates && updates.available.length === 0 ? (
            <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
              当前已是最新版本。
            </Typography.Paragraph>
          ) : (
            <Space direction="vertical" size="small" style={{ marginTop: 12, width: '100%' }}>
              {updates?.available.map((item) => (
                <Space key={item.id} wrap>
                  <Tag color="blue">{kindLabel(item.kind)}</Tag>
                  <Typography.Text>v{item.version}</Typography.Text>
                  {formatSize(item.size_bytes) && (
                    <Typography.Text type="secondary">{formatSize(item.size_bytes)}</Typography.Text>
                  )}
                  {item.forced && <Tag color="red">强制</Tag>}
                  <Button
                    size="small"
                    type="primary"
                    loading={updatingId === item.id}
                    onClick={() => void applyUpdate(item)}
                  >
                    {item.kind === 'app' ? '下载程序包' : '立即更新'}
                  </Button>
                </Space>
              ))}
            </Space>
          )}

          <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
            技能包更新后立即生效;题库、风险规则与量表更新后需重启应用。客户端程序包只会下载到本机,不会自动替换正在运行的程序。
          </Typography.Paragraph>
        </Card>
      )}

      <Card title="应用操作">
        <Space wrap>
          <Button danger loading={loading} onClick={() => void logout()}>
            {desktop ? '退出登录' : '退出当前账号'}
          </Button>
        </Space>
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          {desktop
            ? '退出登录后需要重新用手机号 + 密码登录,本地数据保持不变。'
            : '退出后需要重新用子账号用户名 + 密码登录,本地数据仅保存在桌面端。'}
        </Typography.Paragraph>
      </Card>
    </div>
  )
}
