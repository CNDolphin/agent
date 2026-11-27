import {
  Alert,
  Button,
  Card,
  Descriptions,
  Input,
  Modal,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { api, errorMessage } from '../api'
import { useStatus } from '../status'

export function ProfileDetailPage() {
  const { profileId } = useParams<{ profileId: string }>()
  const { status, refresh } = useStatus()
  const navigate = useNavigate()

  const profile = status?.profiles.find((item) => item.id === profileId)
  const isMain = profile?.role === 'main'

  const [nickname, setNickname] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [note, setNote] = useState('')
  const [ageRange, setAgeRange] = useState('')
  const [active, setActive] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!profile) return
    setNickname(profile.nickname)
    setUsername(profile.username)
    setNote(profile.note)
    setAgeRange(profile.age_range)
    setActive(profile.status === 'active')
  }, [profile?.id, profile?.updated_at, profile])

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

  const current = profile

  async function save() {
    if (!nickname.trim()) {
      setError('昵称不能为空')
      return
    }
    if (!isMain) {
      if (password && (password.length < 8 || password.length > 64)) {
        setError('登录密码需为 8-64 位')
        return
      }
      if (username && (username.length < 3 || username.length > 32)) {
        setError('登录账号需为 3-32 位字母、数字或下划线')
        return
      }
    }
    setSaving(true)
    setError('')
    setNotice('')
    const payload: Record<string, unknown> = {
      nickname: nickname.trim(),
      note,
      age_range: ageRange,
    }
    if (!isMain) {
      if (username && username !== current.username) payload.username = username.trim()
      if (password) payload.password = password
      payload.status = active ? 'active' : 'disabled'
    }
    try {
      await api.patch(`/profiles/${current.id}`, payload)
      setPassword('')
      await refresh()
      setNotice('资料已保存')
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  function remove() {
    Modal.confirm({
      title: '删除子账号',
      content: `将删除「${current.nickname}」的档案目录及其全部会话记录,且无法恢复。是否继续?`,
      okText: '确认删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await api.delete(`/profiles/${current.id}`)
          await refresh()
          navigate('/profiles', { replace: true })
        } catch (err) {
          setError(errorMessage(err))
        }
      },
    })
  }

  return (
    <div className="page-stack">
      <div className="page-head">
        <Space direction="vertical" size={0}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            资料管理
          </Typography.Title>
          <Typography.Text type="secondary">
            {isMain ? '主账号资料与登录密码' : '子账号资料与局域网登录凭据'}
          </Typography.Text>
        </Space>
        <Button onClick={() => navigate('/profiles')}>返回用户管理</Button>
      </div>

      {error && <Alert type="error" showIcon message={error} />}
      {notice && <Alert type="success" showIcon message={notice} />}

      <Card title="基本信息">
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Space wrap>
            {isMain ? <Tag color="blue">主账号</Tag> : <Tag>子账号</Tag>}
            <Tag color={profile.status === 'active' ? 'green' : 'red'}>
              {profile.status === 'active' ? '启用' : '停用'}
            </Tag>
            {profile.id === status?.active_profile?.id && <Tag color="geekblue">当前使用</Tag>}
          </Space>
          <Input
            aria-label="昵称"
            addonBefore="昵称"
            value={nickname}
            onChange={(event) => setNickname(event.target.value)}
          />
          {isMain ? (
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="手机号">
                {status?.phone_mask ?? profile.phone_mask ?? '未登录'}
              </Descriptions.Item>
              <Descriptions.Item label="登录密码">
                请通过登录页「忘记密码」用手机验证码重置
              </Descriptions.Item>
            </Descriptions>
          ) : (
            <>
              <Input
                aria-label="登录账号"
                addonBefore="登录账号"
                value={username}
                onChange={(event) => setUsername(event.target.value.trim())}
              />
              <Input.Password
                aria-label="登录密码"
                addonBefore="登录密码"
                placeholder="留空则不修改"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              <Space>
                <Switch checked={active} onChange={setActive} />
                <Typography.Text>允许该子账号登录(停用后无法通过局域网登录)</Typography.Text>
              </Space>
            </>
          )}
          <Input
            aria-label="年龄段"
            addonBefore="年龄段"
            placeholder="例如 18-25"
            value={ageRange}
            onChange={(event) => setAgeRange(event.target.value)}
          />
          <Input.TextArea
            aria-label="备注"
            placeholder="备注(可选)"
            autoSize={{ minRows: 2, maxRows: 4 }}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </Space>
      </Card>

      <Card title="档案操作">
        <Space wrap>
          <Button type="primary" loading={saving} onClick={() => void save()}>
            保存资料
          </Button>
          <Button onClick={() => navigate(`/profiles/${current.id}/interpretation-report`)}>
            查看解读报告
          </Button>
          <Button onClick={() => navigate('/contact')}>紧急联系人</Button>
          {isMain && (
            <Button onClick={() => navigate('/login?tab=reset')}>重置主账号密码</Button>
          )}
          {!isMain && (
            <Button danger onClick={remove}>
              删除子账号
            </Button>
          )}
        </Space>
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          子账号的会话、量表结果与同意书都保存在独立目录中;删除子账号会同时删除这些数据。
        </Typography.Paragraph>
      </Card>
    </div>
  )
}
