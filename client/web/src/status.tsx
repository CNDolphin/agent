import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { api, clearDeviceToken } from './api'
import type { ConsentInfo, Status } from './types'

interface StatusValue {
  status: Status | null
  latestConsentVersion: string | null
  refresh: () => Promise<Status>
}

const StatusContext = createContext<StatusValue | null>(null)

export function StatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status | null>(null)
  const [latestConsentVersion, setLatestConsentVersion] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    const next = await api.get<Status>('/status')
    setStatus(next)
    if (next.device_mode === 'lan' && !next.logged_in) {
      // 设备令牌失效:清掉本地缓存,回到子账号登录页。
      clearDeviceToken()
    }
    if (next.logged_in) {
      try {
        const consent = await api.get<ConsentInfo>('/consents/latest')
        setLatestConsentVersion(consent.latest.version)
      } catch {
        setLatestConsentVersion(null)
      }
    } else {
      setLatestConsentVersion(null)
    }
    return next
  }, [])

  useEffect(() => {
    refresh().catch(() => setStatus(null))
  }, [refresh])

  return (
    <StatusContext.Provider value={{ status, latestConsentVersion, refresh }}>
      {children}
    </StatusContext.Provider>
  )
}

export function useStatus(): StatusValue {
  const value = useContext(StatusContext)
  if (!value) {
    throw new Error('useStatus 必须在 StatusProvider 内使用')
  }
  return value
}
