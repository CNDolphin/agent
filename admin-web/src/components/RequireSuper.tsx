import type { ReactNode } from 'react'
import { Result } from 'antd'
import { useSessionRole } from '../api/session'

export function RequireSuper({ children }: { children: ReactNode }) {
  const role = useSessionRole()

  if (role !== 'super') {
    return (
      <Result
        status="403"
        title="无权访问"
        subTitle="该功能仅限超级管理员（super）使用，如有需要请联系超级管理员。"
      />
    )
  }

  return <>{children}</>
}
