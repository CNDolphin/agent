import { Alert, Button, Card, Input, Radio, Space, Switch, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, errorMessage } from '../api'
import type { ContactState } from '../types'

export function ContactPage() {
  const navigate = useNavigate()
  const [channel, setChannel] = useState<'sms' | 'email'>('sms')
  const [value, setValue] = useState('')
  const [authorized, setAuthorized] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api
      .get<ContactState>('/contact')
      .then((state) => {
        if (state.channel) {
          setChannel(state.channel)
          setValue(state.contact ?? '')
          setAuthorized(state.emergency_authorized)
        }
      })
      .catch(() => undefined)
  }, [])

  async function save() {
    if (!value.trim()) {
      setError('请填写联系人的手机号或邮箱')
      return
    }
    setLoading(true)
    setError('')
    try {
      await api.post('/contact', { channel, value: value.trim(), authorized })
      setNotice('紧急联系人已保存')
      navigate('/', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function revoke() {
    try {
      await api.delete('/contact')
      setAuthorized(false)
      setNotice('已关闭高风险时的紧急通知')
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="center-page">
      <Card className="narrow-card">
        <Typography.Title level={3}>紧急联系人(可选)</Typography.Title>
        <Typography.Paragraph type="secondary">
          只有在你单独开启「高风险时通知」后,系统才会在你表达高风险时向该联系人发送一条通知。
          后端发送后不保存联系方式,你也可以随时关闭或跳过。
        </Typography.Paragraph>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Radio.Group
            value={channel}
            onChange={(event) => setChannel(event.target.value as 'sms' | 'email')}
          >
            <Radio.Button value="sms">短信</Radio.Button>
            <Radio.Button value="email">邮箱</Radio.Button>
          </Radio.Group>
          <Input
            aria-label="联系人"
            placeholder={channel === 'sms' ? '紧急联系人手机号' : '紧急联系人邮箱'}
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
          <Space>
            <Switch checked={authorized} onChange={setAuthorized} />
            <Typography.Text>高风险时通知该联系人</Typography.Text>
          </Space>
          {notice && <Alert type="info" showIcon message={notice} />}
          {error && <Alert type="error" showIcon message={error} />}
          <Button type="primary" block loading={loading} onClick={() => void save()}>
            保存并继续
          </Button>
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Button type="link" onClick={() => navigate('/', { replace: true })}>
              跳过
            </Button>
            {authorized && (
              <Button type="link" danger onClick={() => void revoke()}>
                关闭通知授权
              </Button>
            )}
          </Space>
        </Space>
      </Card>
    </div>
  )
}
