import { Spin, notification } from 'antd'
import type { ReactNode } from 'react'
import { useEffect } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'

import { api } from './api'
import { AppShell } from './components/AppShell'
import { AssessmentPage } from './pages/AssessmentPage'
import { ChatPage } from './pages/ChatPage'
import { ConsentPage } from './pages/ConsentPage'
import { ContactPage } from './pages/ContactPage'
import { CreditsPage } from './pages/CreditsPage'
import { LegacyMigratePage } from './pages/LegacyMigratePage'
import { LoginPage } from './pages/LoginPage'
import { InterpretationReportPage } from './pages/InterpretationReportPage'
import { OnboardingPage } from './pages/OnboardingPage'
import { PracticesPage } from './pages/PracticesPage'
import { ProfileDetailPage } from './pages/ProfileDetailPage'
import { ProfilesPage } from './pages/ProfilesPage'
import { ReportsPage } from './pages/ReportsPage'
import { SettingsPage } from './pages/SettingsPage'
import { useStatus } from './status'

function Loading() {
  return (
    <div className="center-page">
      <Spin size="large" tip="正在连接本地服务…">
        <div className="spin-holder" />
      </Spin>
    </div>
  )
}

interface UpdateStatus {
  app_version: string
  available: Array<{ id: number; kind: string; version: string }>
}

/** 登录后检查一次更新,有新版本时提示一次(同一批版本只提示一次)。 */
function UpdateNotifier() {
  const { status } = useStatus()
  const navigate = useNavigate()
  const loggedIn = Boolean(status?.logged_in)
  const desktop = status?.device_mode === 'desktop'

  useEffect(() => {
    if (!loggedIn || !desktop) return
    let cancelled = false
    const run = async () => {
      let data = await api.get<UpdateStatus>('/updates')
      if (!cancelled && data.available.length === 0) {
        data = await api.post<UpdateStatus>('/updates/check')
      }
      if (cancelled || data.available.length === 0) return
      const signature = data.available
        .map((item) => `${item.kind}-${item.version}`)
        .sort()
        .join(',')
      const key = `mhagent.update-notice.${data.app_version}.${signature}`
      try {
        if (window.sessionStorage.getItem(key)) return
        window.sessionStorage.setItem(key, '1')
      } catch {
        // sessionStorage 不可用时仍然提示一次。
      }
      notification.info({
        message: '发现新的更新内容',
        description: `共有 ${data.available.length} 项可更新,前往设置页查看。`,
        placement: 'bottomRight',
        duration: 8,
        onClick: () => {
          notification.destroy()
          navigate('/settings')
        },
      })
    }
    run().catch(() => {
      // 更新检查失败不影响正常使用。
    })
    return () => {
      cancelled = true
    }
  }, [loggedIn, desktop, navigate])

  return null
}

function Protected({ children, desktopOnly = false }: { children: ReactNode; desktopOnly?: boolean }) {
  const { status, latestConsentVersion } = useStatus()
  if (!status) return <Loading />
  if (status.legacy_required) return <Navigate to="/migrate" replace />
  if (!status.logged_in) return <Navigate to="/login" replace />
  if (desktopOnly && status.device_mode !== 'desktop') return <Navigate to="/" replace />
  if (status.consent_version === null) return <Navigate to="/consent" replace />
  if (latestConsentVersion && latestConsentVersion !== status.consent_version) {
    return <Navigate to="/consent" replace />
  }
  return <AppShell>{children}</AppShell>
}

export default function App() {
  return (
    <>
      <UpdateNotifier />
      <Routes>
        <Route path="/migrate" element={<LegacyMigratePage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/consent" element={<ConsentPage />} />
        <Route path="/contact" element={<ContactPage />} />
        <Route
          path="/"
          element={
            <Protected>
              <ChatPage />
            </Protected>
          }
        />
        <Route
          path="/onboarding"
          element={
            <Protected>
              <OnboardingPage />
            </Protected>
          }
        />
        <Route path="/sessions" element={<Navigate to="/" replace />} />
        <Route
          path="/assessment"
          element={
            <Protected>
              <AssessmentPage />
            </Protected>
          }
        />
        <Route
          path="/practices"
          element={
            <Protected>
              <PracticesPage />
            </Protected>
          }
        />
        <Route
          path="/reports"
          element={
            <Protected desktopOnly>
              <ReportsPage />
            </Protected>
          }
        />
        <Route
          path="/credits"
          element={
            <Protected desktopOnly>
              <CreditsPage />
            </Protected>
          }
        />
        <Route
          path="/profiles"
          element={
            <Protected desktopOnly>
              <ProfilesPage />
            </Protected>
          }
        />
        <Route
          path="/profiles/:profileId"
          element={
            <Protected desktopOnly>
              <ProfileDetailPage />
            </Protected>
          }
        />
        <Route
          path="/profiles/:profileId/interpretation-report"
          element={
            <Protected desktopOnly>
              <InterpretationReportPage />
            </Protected>
          }
        />
        <Route
          path="/settings"
          element={
            <Protected>
              <SettingsPage />
            </Protected>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}
