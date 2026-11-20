import { Badge, Layout, Menu, Tag, Typography, notification } from 'antd'
import type { MenuProps } from 'antd'
import type { ReactNode } from 'react'
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { api } from '../api'
import { REPORTS_UPDATED_EVENT } from '../pages/ReportsPage'
import { useStatus } from '../status'

const { Header, Sider, Content } = Layout

const CURRENT_ITEMS: NonNullable<MenuProps['items']> = [
  { key: '/', label: '对话支持' },
  { key: '/onboarding', label: '基础测评' },
  { key: '/assessment', label: '量表评估' },
  { key: '/practices', label: '放松练习' },
]

const MANAGE_ITEMS: NonNullable<MenuProps['items']> = [
  { key: '/credits', label: '积分与套餐' },
  { key: '/profiles', label: '用户管理' },
]

function selectedKey(pathname: string): string {
  if (pathname.startsWith('/profiles')) return '/profiles'
  const keys = [
    '/',
    '/onboarding',
    '/assessment',
    '/practices',
    '/reports',
    '/credits',
    '/settings',
  ]
  return keys.find((key) => key === pathname) ?? '/'
}

/** 未读数轮询间隔:报告通过后端推送落到本地后,角标最迟 30 秒更新。 */
const UNREAD_POLL_MS = 30000

export function AppShell({ children }: { children: ReactNode }) {
  const { status } = useStatus()
  const location = useLocation()
  const navigate = useNavigate()
  const isDesktop = status?.device_mode === 'desktop'
  const showReports = isDesktop && status?.active_profile?.role === 'main'
  const [unread, setUnread] = useState(0)
  const lastUnread = useRef(0)
  const [notificationApi, notificationHolder] = notification.useNotification()

  useEffect(() => {
    if (!showReports) {
      setUnread(0)
      lastUnread.current = 0
      return
    }
    let cancelled = false

    async function poll() {
      try {
        const data = await api.get<{ count: number }>('/reports/unread-count')
        if (cancelled) return
        const count = Number(data.count) || 0
        if (count > lastUnread.current) {
          notificationApi.info({
            message: '收到新的检测报告',
            description: '报告已自动下载到本机文档目录,可在「我的报告」中查看。',
            placement: 'topRight',
          })
        }
        lastUnread.current = count
        setUnread(count)
      } catch {
        // 轮询失败不打扰用户,下一轮自动重试。
      }
    }

    void poll()
    const timer = setInterval(() => void poll(), UNREAD_POLL_MS)
    window.addEventListener(REPORTS_UPDATED_EVENT, poll)
    return () => {
      cancelled = true
      clearInterval(timer)
      window.removeEventListener(REPORTS_UPDATED_EVENT, poll)
    }
  }, [showReports, notificationApi])

  const currentItems: NonNullable<MenuProps['items']> = showReports
    ? [
        ...CURRENT_ITEMS,
        {
          key: '/reports',
          label: (
            <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              我的报告
              {unread > 0 && <Badge count={unread} size="small" />}
            </span>
          ),
        },
      ]
    : CURRENT_ITEMS

  const items: MenuProps['items'] = [
    {
      key: 'current',
      label: '当前档案',
      type: 'group',
      children: currentItems,
    },
    {
      key: 'manage',
      label: '管理',
      type: 'group',
      children: [
        ...(isDesktop ? MANAGE_ITEMS : []),
        { key: '/settings', label: '设置' },
      ],
    },
  ]

  return (
    <Layout className="app-shell">
      {notificationHolder}
      <Sider
        width={200}
        theme="light"
        breakpoint="lg"
        collapsedWidth={0}
        className="app-sider"
      >
        <div className="brand">
          <span className="brand-mark">安</span>
          <span className="brand-name">本地心理助手</span>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey(location.pathname)]}
          items={items}
          onClick={({ key }) => navigate(key)}
        />
        <div className="sider-footnote">
          数据只保存在本机
          <br />
          热线 12356 / 120
        </div>
      </Sider>
      <Layout>
        <Header className="app-header">
          <Typography.Text strong>安心陪伴</Typography.Text>
          <div className="header-tags">
            {status?.active_profile && (
              <Tag color="geekblue">{status.active_profile.nickname}</Tag>
            )}
            {status?.phone_mask && <Tag color="blue">{status.phone_mask}</Tag>}
            {status?.device_mode === 'lan' ? (
              <Tag color="orange">局域网设备</Tag>
            ) : (
              <Tag color="green">本地加密存储</Tag>
            )}
          </div>
        </Header>
        <Content className="app-content">{children}</Content>
      </Layout>
    </Layout>
  )
}
