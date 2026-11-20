import { useState } from 'react'
import { Alert, App as AntApp, Button, Form, Input } from 'antd'
import { useNavigate } from 'react-router-dom'
import { login } from '../api/admin'
import { ApiError } from '../api/client'
import { saveSession } from '../api/session'
import { BrandMark } from '../components/BrandMark'

interface LoginFormValues {
  username: string
  password: string
}

export function LoginPage() {
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (values: LoginFormValues) => {
    setLoading(true)
    setError(null)
    try {
      const result = await login(values.username.trim(), values.password)
      saveSession({
        token: result.access_token,
        role: result.role,
        username: result.username ?? values.username.trim(),
      })
      message.success('登录成功')
      navigate('/prices', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '登录失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-shell">
      <aside className="login-plate">
        <div className="plate-brand">
          <BrandMark size={34} />
          <div>
            <div className="plate-name">MHA // LAB</div>
            <div className="plate-sub">心理健康 · 基因检测运营台</div>
          </div>
        </div>

        <div className="plate-body">
          <div className="plate-kicker">OPERATIONS LEDGER · 2026</div>
          <h2 className="plate-title">
            把每一次对话，
            <br />
            当作一次<em>临床观察</em>。
          </h2>
          <p className="plate-copy">
            积分、用量、检测报告与通知记录，都在这本台账里留下可追溯的记录。
            对话内容留在用户自己的设备上，后台只看见必要的运营数字。
          </p>
        </div>

        <div>
          <svg
            className="plate-wave"
            viewBox="0 0 520 84"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <path
              className="helix"
              d="M0 30C40 10 80 50 120 30S200 10 240 30S320 50 360 30S440 10 480 30S520 34 520 30"
            />
            <path
              className="helix"
              d="M0 54C40 74 80 34 120 54S200 74 240 54S320 34 360 54S440 74 480 54S520 50 520 54"
            />
            <path d="M0 44H150L164 44L174 18L190 72L204 32L216 44H330L344 44L354 26L368 62L380 44H520" />
            <path
              className="pulse"
              d="M0 44H180L192 44L202 36L214 52L226 44H520"
            />
          </svg>

          <dl className="plate-ledger">
            <div>
              <dt>DEPLOY</dt>
              <dd>本地设备运行</dd>
            </div>
            <div>
              <dt>STORAGE</dt>
              <dd>仅积分与用量</dd>
            </div>
            <div>
              <dt>DIALOGUE</dt>
              <dd>对话零留存</dd>
            </div>
          </dl>
        </div>
      </aside>

      <main className="login-form-side">
        <section className="login-sheet" aria-labelledby="login-title">
          <div className="login-kicker">ADMIN ACCESS / 管理层</div>
          <h1 className="login-title" id="login-title">
            管理后台登录
          </h1>
          <p className="login-sub">心理健康 Agent 运营管理系统</p>

          {error ? (
            <Alert
              type="error"
              showIcon
              title={error}
              style={{ marginBottom: 16 }}
              closable
              onClose={() => setError(null)}
            />
          ) : null}

          <Form<LoginFormValues>
            layout="vertical"
            requiredMark={false}
            onFinish={handleSubmit}
            disabled={loading}
          >
            <Form.Item
              label="用户名"
              name="username"
              rules={[{ required: true, message: '请输入用户名' }]}
            >
              <Input placeholder="管理员用户名" autoComplete="username" />
            </Form.Item>
            <Form.Item
              label="密码"
              name="password"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password placeholder="管理员密码" autoComplete="current-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              登录
            </Button>
          </Form>

          <div className="login-foot">
            <span>MHA // LAB</span>
            <span>仅限授权人员</span>
          </div>
        </section>
      </main>
    </div>
  )
}
