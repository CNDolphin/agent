import type { ReactNode } from 'react'
import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AdminLayout } from './components/AdminLayout'
import { RequireAuth } from './components/RequireAuth'
import { RequireSuper } from './components/RequireSuper'
import { ContentPage } from './pages/ContentPage'
import { GrantPage } from './pages/GrantPage'
import { LoginPage } from './pages/LoginPage'
import { NotifyLogsPage } from './pages/NotifyLogsPage'
import { OrdersPage } from './pages/OrdersPage'
import { PackagesPage } from './pages/PackagesPage'
import { PricesPage } from './pages/PricesPage'
import { ReportsPage } from './pages/ReportsPage'
import { UsagePage } from './pages/UsagePage'
import { UsersPage } from './pages/UsersPage'
import { adminTheme } from './theme'

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={adminTheme}
      button={{ autoInsertSpace: false }}
      wave={{ disabled: true }}
    >
      <AntApp>{children}</AntApp>
    </ConfigProvider>
  )
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AdminLayout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/prices" replace />} />
        <Route path="prices" element={<PricesPage />} />
        <Route path="packages" element={<PackagesPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="users" element={<UsersPage />} />
        <Route
          path="credits/grant"
          element={
            <RequireSuper>
              <GrantPage />
            </RequireSuper>
          }
        />
        <Route path="usage" element={<UsagePage />} />
        <Route path="notify-logs" element={<NotifyLogsPage />} />
        <Route
          path="reports"
          element={
            <RequireSuper>
              <ReportsPage />
            </RequireSuper>
          }
        />
        <Route
          path="contents"
          element={
            <RequireSuper>
              <ContentPage />
            </RequireSuper>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <AppProviders>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AppProviders>
  )
}
