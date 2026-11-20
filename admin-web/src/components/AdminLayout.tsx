import { App as AntApp, Button, Layout, Menu } from 'antd'
import type { MenuProps } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { clearSession, getUsername, useSessionRole } from '../api/session'
import { BrandMark } from './BrandMark'

const { Header, Sider, Content } = Layout

interface ModuleItem {
  key: string
  code: string
  label: string
  superOnly?: boolean
}

/** 台账模块编号：编号本身是导航结构，不是装饰。 */
const MODULES: ModuleItem[] = [
  { key: '/prices', code: 'M-01', label: '模型定价' },
  { key: '/packages', code: 'M-02', label: '套餐管理' },
  { key: '/orders', code: 'M-03', label: '订单管理' },
  { key: '/users', code: 'M-04', label: '用户查询' },
  { key: '/usage', code: 'M-05', label: '用量汇总' },
  { key: '/notify-logs', code: 'M-06', label: '通知记录' },
  { key: '/credits/grant', code: 'M-07', label: '积分发放', superOnly: true },
  { key: '/reports', code: 'M-08', label: '检测报告', superOnly: true },
  { key: '/contents', code: 'M-09', label: '内容更新', superOnly: true },
]

function currentModule(pathname: string): ModuleItem {
  return MODULES.find((item) => pathname.startsWith(item.key)) ?? MODULES[0]
}

function today(): string {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}.${pad(now.getMonth() + 1)}.${pad(now.getDate())}`
}

function HelixSpine() {
  return (
    <div className="sider-helix" aria-hidden="true">
      <svg viewBox="0 0 26 96" preserveAspectRatio="none">
        <defs>
          <pattern id="helix-tile" width="26" height="96" patternUnits="userSpaceOnUse">
            <path
              d="M6 0C20 12 20 36 6 48C-8 60-8 84 6 96"
              fill="none"
              stroke="#3E8F8A"
              strokeWidth="1"
            />
            <path
              d="M20 0C6 12 6 36 20 48C34 60 34 84 20 96"
              fill="none"
              stroke="#3E8F8A"
              strokeWidth="1"
            />
            <g stroke="#6FE3D6" strokeWidth="0.8" opacity="0.6">
              <path d="M11 8h6M9.5 20h6M9.5 32h6M9.5 64h6M9.5 76h6M11 88h6" />
            </g>
          </pattern>
        </defs>
        <rect width="26" height="100%" fill="url(#helix-tile)" />
      </svg>
    </div>
  )
}

export function AdminLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const role = useSessionRole()
  const { message } = AntApp.useApp()
  const username = getUsername()

  const visible = MODULES.filter((item) => role === 'super' || !item.superOnly)
  const menuItems: NonNullable<MenuProps['items']> = visible.map((item) => ({
    key: item.key,
    label: (
      <span className="menu-item">
        <span className="menu-code">{item.code}</span>
        <span className="menu-label">{item.label}</span>
      </span>
    ),
  }))
  const active = currentModule(location.pathname)

  const handleLogout = () => {
    clearSession()
    message.success('已退出登录')
    navigate('/login', { replace: true })
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider className="admin-sider" width={216} breakpoint="lg" collapsedWidth={64}>
        <HelixSpine />
        <div className="sider-inner">
          <div className="brand">
            <BrandMark />
            <div className="brand-text">
              <div className="brand-name">MHA // LAB</div>
              <div className="brand-sub">心理 · 基因检测运营台</div>
            </div>
          </div>
          <Menu
            className="admin-menu"
            theme="dark"
            mode="inline"
            selectedKeys={[active.key]}
            items={menuItems}
            onClick={({ key }) => navigate(String(key))}
            style={{ marginTop: 10 }}
          />
          <div className="sider-foot">
            <span>LOCAL-FIRST</span>
            <span>v0.1</span>
          </div>
        </div>
      </Sider>
      <Layout>
        <Header className="admin-header">
          <div className="top-meta">
            <span className="crumb-code">{active.code}</span>
            <span className="crumb-slash" aria-hidden="true">
              /
            </span>
            <span className="crumb-name">{active.label}</span>
            <span className="crumb-sep" aria-hidden="true" />
            <span className="crumb-date">{today()}</span>
          </div>
          <div className="top-user">
            <span className="user-name">{username ?? '管理员'}</span>
            <span className={`chip-role ${role === 'super' ? 'chip-super' : 'chip-ops'}`}>
              {role === 'super' ? 'SUPER ADMIN' : 'OPERATOR'}
            </span>
            <span className="top-divider" aria-hidden="true" />
            <Button className="logout-btn" type="text" size="small" onClick={handleLogout}>
              退出登录
            </Button>
          </div>
        </Header>
        <Content className="admin-content">
          <div className="admin-content-inner">
            <Outlet />
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}
