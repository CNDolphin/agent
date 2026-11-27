import { Alert, Button, Card, Input, Modal, Space, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, errorMessage } from '../api'
import { useStatus } from '../status'
import type { Profile } from '../types'

interface CreateForm {
  nickname: string
  username: string
  password: string
  note: string
  age_range: string
}

const EMPTY_FORM: CreateForm = {
  nickname: '',
  username: '',
  password: '',
  note: '',
  age_range: '',
}

export function ProfilesPage() {
  const { status, refresh } = useStatus()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const profiles = status?.profiles ?? []
  const activeId = status?.active_profile?.id

  function update<K extends keyof CreateForm>(key: K, value: CreateForm[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  async function create() {
    if (!form.nickname.trim()) {
      setError('昵称不能为空')
      return
    }
    if (!form.username.trim()) {
      setError('请填写登录账号')
      return
    }
    if (form.password.length < 8 || form.password.length > 64) {
      setError('登录密码需为 8-64 位')
      return
    }
    setSaving(true)
    setError('')
    try {
      await api.post('/profiles', {
        nickname: form.nickname.trim(),
        username: form.username.trim(),
        password: form.password,
        note: form.note,
        age_range: form.age_range,
      })
      setOpen(false)
      setForm(EMPTY_FORM)
      await refresh()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function activate(profile: Profile) {
    setError('')
    try {
      await api.post(`/profiles/${profile.id}/activate`)
      await refresh()
      navigate('/', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function toggleStatus(profile: Profile) {
    setError('')
    try {
      await api.patch(`/profiles/${profile.id}`, {
        status: profile.status === 'active' ? 'disabled' : 'active',
      })
      await refresh()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  function remove(profile: Profile) {
    Modal.confirm({
      title: '删除子账号',
      content: `将删除「${profile.nickname}」的档案目录及其全部会话记录,且无法恢复。是否继续?`,
      okText: '确认删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await api.delete(`/profiles/${profile.id}`)
          await refresh()
        } catch (err) {
          setError(errorMessage(err))
        }
      },
    })
  }

  const columns: TableColumnsType<Profile> = [
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      width: 90,
      render: (value: string) =>
        value === 'main' ? <Tag color="blue">主账号</Tag> : <Tag>子账号</Tag>,
    },
    { title: '昵称', dataIndex: 'nickname', key: 'nickname' },
    {
      title: '登录账号',
      dataIndex: 'username',
      key: 'username',
      render: (value: string, profile) => value || profile.phone_mask || '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (value: string) =>
        value === 'active' ? <Tag color="green">启用</Tag> : <Tag color="red">停用</Tag>,
    },
    {
      title: '备注',
      dataIndex: 'note',
      key: 'note',
      render: (value: string, profile) => value || profile.age_range || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 360,
      render: (_, profile) => (
        <Space wrap>
          {profile.id === activeId ? (
            <Tag color="geekblue">当前使用</Tag>
          ) : (
            <Button
              size="small"
              type="primary"
              disabled={profile.status !== 'active'}
              onClick={() => void activate(profile)}
            >
              切换
            </Button>
          )}
          <Button size="small" onClick={() => navigate(`/profiles/${profile.id}`)}>
            编辑
          </Button>
          <Button
            size="small"
            onClick={() => navigate(`/profiles/${profile.id}/interpretation-report`)}
          >
            解读报告
          </Button>
          {profile.role === 'sub' && (
            <>
              <Button size="small" onClick={() => void toggleStatus(profile)}>
                {profile.status === 'active' ? '停用' : '启用'}
              </Button>
              <Button size="small" danger onClick={() => remove(profile)}>
                删除
              </Button>
            </>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div className="page-stack">
      <div className="page-head">
        <Space direction="vertical" size={0}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            用户管理
          </Typography.Title>
          <Typography.Text type="secondary">
            子账号只保存在本机,可用用户名 + 密码在局域网内通过浏览器/手机登录;
            所有子账号共用主账号积分与会话隔离目录。
          </Typography.Text>
        </Space>
        <Button type="primary" onClick={() => setOpen(true)}>
          新建子账号
        </Button>
      </div>

      {error && <Alert type="error" showIcon message={error} />}

      <Card>
        <Table<Profile>
          rowKey="id"
          columns={columns}
          dataSource={profiles}
          pagination={false}
        />
      </Card>

      <Modal
        open={open}
        title="新建子账号"
        okText="创建"
        cancelText="取消"
        confirmLoading={saving}
        onOk={() => void create()}
        onCancel={() => {
          setOpen(false)
          setForm(EMPTY_FORM)
          setError('')
        }}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Input
            aria-label="昵称"
            placeholder="昵称(例如:小明)"
            value={form.nickname}
            onChange={(event) => update('nickname', event.target.value)}
          />
          <Input
            aria-label="登录账号"
            placeholder="登录账号(3-32 位字母、数字或下划线)"
            value={form.username}
            onChange={(event) => update('username', event.target.value.trim())}
          />
          <Input.Password
            aria-label="登录密码"
            placeholder="登录密码(8-64 位)"
            value={form.password}
            onChange={(event) => update('password', event.target.value)}
          />
          <Input
            aria-label="年龄段"
            placeholder="年龄段(可选,例如 18-25)"
            value={form.age_range}
            onChange={(event) => update('age_range', event.target.value)}
          />
          <Input.TextArea
            aria-label="备注"
            autoSize={{ minRows: 2, maxRows: 4 }}
            placeholder="备注(可选)"
            value={form.note}
            onChange={(event) => update('note', event.target.value)}
          />
          {error && <Alert type="error" showIcon message={error} />}
        </Space>
      </Modal>
    </div>
  )
}
