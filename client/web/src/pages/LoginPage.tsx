import { Alert, Button, Card, Input, Space, Tabs, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { ApiError, api, errorMessage, setDeviceToken } from '../api'
import { useStatus } from '../status'
import type { DeviceLoginResult, LoginResult } from '../types'

const PHONE_RE = /^1[3-9]\d{9}$/
const PASSWORD_MIN = 8
const PASSWORD_MAX = 64

type TabKey = 'login' | 'register' | 'reset'

function passwordProblem(value: string): string {
  if (value.length < PASSWORD_MIN || value.length > PASSWORD_MAX) {
    return `密码长度需为 ${PASSWORD_MIN}-${PASSWORD_MAX} 位`
  }
  return ''
}

export function LoginPage() {
  const { status, refresh } = useStatus()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const lan = status?.device_mode === 'lan'

  const [tab, setTab] = useState<TabKey>(searchParams.get('tab') === 'reset' ? 'reset' : 'login')
  const [phone, setPhone] = useState('')
  const [registerPhone, setRegisterPhone] = useState('')
  const [resetPhone, setResetPhone] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [registerPassword, setRegisterPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [registerCode, setRegisterCode] = useState('')
  const [resetCode, setResetCode] = useState('')
  const [seconds, setSeconds] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (seconds <= 0) return
    const timer = setInterval(() => setSeconds((value) => (value > 0 ? value - 1 : 0)), 1000)
    return () => clearInterval(timer)
  }, [seconds])

  function resetMessages() {
    setError('')
    setNotice('')
  }

  async function sendCode(target: string): Promise<boolean> {
    if (!PHONE_RE.test(target)) {
      setError('请输入中国大陆 11 位手机号')
      return false
    }
    setError('')
    setNotice('')
    try {
      await api.post('/auth/send-code', { phone: target })
      setSeconds(60)
      setNotice('验证码已发送,请查收短信')
      return true
    } catch (err) {
      setError(errorMessage(err))
      return false
    }
  }

  async function fetchDevCode(target: string): Promise<string | null> {
    if (!PHONE_RE.test(target)) {
      setError('请先填写手机号')
      return null
    }
    try {
      const data = await api.get<{ code: string }>(`/dev/sms-code?phone=${target}`)
      setNotice(`开发验证码已填入:${data.code}`)
      setError('')
      return data.code
    } catch (err) {
      setError(errorMessage(err))
      return null
    }
  }

  async function afterLogin(result: LoginResult) {
    const next = await refresh()
    if (result.is_new) {
      setNotice('首次登录已自动注册,获赠 100 积分。')
    }
    navigate(next.consent_version ? '/' : '/consent', { replace: true })
  }

  async function submitLogin() {
    if (!PHONE_RE.test(phone)) {
      setError('请输入中国大陆 11 位手机号')
      return
    }
    if (!password.trim()) {
      setError('请输入密码')
      return
    }
    resetMessages()
    setLoading(true)
    try {
      const result = await api.post<LoginResult>('/auth/login', { phone, password })
      await afterLogin(result)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'password_required') {
        setError('该手机号尚未设置密码,请用「忘记密码」通过手机验证码设置后再登录。')
      } else {
        setError(errorMessage(err))
      }
    } finally {
      setLoading(false)
    }
  }

  async function submitRegister() {
    if (!PHONE_RE.test(registerPhone)) {
      setError('请输入中国大陆 11 位手机号')
      return
    }
    if (!registerCode.trim()) {
      setError('请输入验证码')
      return
    }
    const problem = passwordProblem(registerPassword)
    if (problem) {
      setError(problem)
      return
    }
    resetMessages()
    setLoading(true)
    try {
      const result = await api.post<LoginResult>('/auth/register', {
        phone: registerPhone,
        code: registerCode.trim(),
        password: registerPassword,
      })
      await afterLogin(result)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'already_registered') {
        setError('该手机号已注册并设置了密码,请直接登录。')
      } else {
        setError(errorMessage(err))
      }
    } finally {
      setLoading(false)
    }
  }

  async function submitReset() {
    if (!PHONE_RE.test(resetPhone)) {
      setError('请输入中国大陆 11 位手机号')
      return
    }
    if (!resetCode.trim()) {
      setError('请输入验证码')
      return
    }
    const problem = passwordProblem(newPassword)
    if (problem) {
      setError(problem)
      return
    }
    resetMessages()
    setLoading(true)
    try {
      await api.post('/auth/reset-password', {
        phone: resetPhone,
        code: resetCode.trim(),
        new_password: newPassword,
      })
      setPhone(resetPhone)
      setPassword('')
      setNewPassword('')
      setResetCode('')
      setTab('login')
      setNotice('密码已重置,请用新密码登录。')
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function submitDeviceLogin() {
    if (!username.trim()) {
      setError('请输入登录账号')
      return
    }
    if (!password.trim()) {
      setError('请输入登录密码')
      return
    }
    resetMessages()
    setLoading(true)
    try {
      const result = await api.post<DeviceLoginResult>('/device/login', {
        username: username.trim(),
        password,
      })
      setDeviceToken(result.device_token)
      const next = await refresh()
      navigate(next.consent_version ? '/' : '/consent', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const devMode = Boolean(status?.dev_mode)

  if (lan) {
    return (
      <div className="center-page">
        <Card className="narrow-card">
          <Typography.Title level={3}>子账号登录</Typography.Title>
          <Typography.Paragraph type="secondary">
            请使用主账号在桌面端「用户管理」中为你创建的登录账号与密码。
            局域网访问为明文 HTTP,请仅在可信网络内使用。
          </Typography.Paragraph>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Input
              aria-label="登录账号"
              placeholder="请输入登录账号"
              value={username}
              autoFocus
              onChange={(event) => setUsername(event.target.value.trim())}
            />
            <Input.Password
              aria-label="登录密码"
              placeholder="请输入登录密码"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              onPressEnter={() => void submitDeviceLogin()}
            />
            {notice && <Alert type="info" showIcon message={notice} />}
            {error && <Alert type="error" showIcon message={error} />}
            <Button
              type="primary"
              block
              loading={loading}
              onClick={() => void submitDeviceLogin()}
            >
              登录
            </Button>
          </Space>
        </Card>
      </div>
    )
  }

  const loginPane = (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Input
        aria-label="手机号"
        placeholder="请输入手机号"
        value={phone}
        maxLength={11}
        onChange={(event) => setPhone(event.target.value.trim())}
      />
      <Input.Password
        aria-label="密码"
        placeholder="请输入密码"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        onPressEnter={() => void submitLogin()}
      />
      {notice && <Alert type="info" showIcon message={notice} />}
      {error && <Alert type="error" showIcon message={error} />}
      <Button type="primary" block loading={loading} onClick={() => void submitLogin()}>
        登录
      </Button>
    </Space>
  )

  const registerPane = (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Input
        aria-label="注册手机号"
        placeholder="请输入手机号"
        value={registerPhone}
        maxLength={11}
        onChange={(event) => setRegisterPhone(event.target.value.trim())}
      />
      <Space.Compact style={{ width: '100%' }}>
        <Input
          aria-label="注册验证码"
          placeholder="请输入验证码"
          value={registerCode}
          maxLength={6}
          onChange={(event) => setRegisterCode(event.target.value.trim())}
        />
        <Button disabled={seconds > 0} onClick={() => void sendCode(registerPhone)}>
          {seconds > 0 ? `重新发送(${seconds}s)` : '发送验证码'}
        </Button>
      </Space.Compact>
      {devMode && (
        <Button
          type="link"
          onClick={() => {
            void fetchDevCode(registerPhone).then((code) => {
              if (code) setRegisterCode(code)
            })
          }}
        >
          获取开发验证码
        </Button>
      )}
      <Input.Password
        aria-label="设置密码"
        placeholder="设置登录密码（8-64 位）"
        value={registerPassword}
        onChange={(event) => setRegisterPassword(event.target.value)}
        onPressEnter={() => void submitRegister()}
      />
      {notice && <Alert type="info" showIcon message={notice} />}
      {error && <Alert type="error" showIcon message={error} />}
      <Button type="primary" block loading={loading} onClick={() => void submitRegister()}>
        注册并登录
      </Button>
    </Space>
  )

  const resetPane = (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Input
        aria-label="重置手机号"
        placeholder="请输入手机号"
        value={resetPhone}
        maxLength={11}
        onChange={(event) => setResetPhone(event.target.value.trim())}
      />
      <Space.Compact style={{ width: '100%' }}>
        <Input
          aria-label="重置验证码"
          placeholder="请输入验证码"
          value={resetCode}
          maxLength={6}
          onChange={(event) => setResetCode(event.target.value.trim())}
        />
        <Button disabled={seconds > 0} onClick={() => void sendCode(resetPhone)}>
          {seconds > 0 ? `重新发送(${seconds}s)` : '发送重置验证码'}
        </Button>
      </Space.Compact>
      {devMode && (
        <Button
          type="link"
          onClick={() => {
            void fetchDevCode(resetPhone).then((code) => {
              if (code) setResetCode(code)
            })
          }}
        >
          获取重置验证码
        </Button>
      )}
      <Input.Password
        aria-label="新密码"
        placeholder="设置新密码（8-64 位）"
        value={newPassword}
        onChange={(event) => setNewPassword(event.target.value)}
        onPressEnter={() => void submitReset()}
      />
      {notice && <Alert type="info" showIcon message={notice} />}
      {error && <Alert type="error" showIcon message={error} />}
      <Button type="primary" block loading={loading} onClick={() => void submitReset()}>
        重置密码
      </Button>
    </Space>
  )

  return (
    <div className="center-page">
      <Card className="narrow-card">
        <Typography.Title level={3}>登录本地助手</Typography.Title>
        <Typography.Paragraph type="secondary">
          使用手机号 + 密码登录主账号。首次使用请在「首次注册」中用手机验证码设置密码;
          忘记密码可通过验证码重置。
        </Typography.Paragraph>
        <Tabs
          activeKey={tab}
          onChange={(key) => {
            resetMessages()
            setTab(key as TabKey)
          }}
          items={[
            { key: 'login', label: '登录', children: loginPane },
            { key: 'register', label: '首次注册', children: registerPane },
            { key: 'reset', label: '忘记密码', children: resetPane },
          ]}
        />
      </Card>
    </div>
  )
}
