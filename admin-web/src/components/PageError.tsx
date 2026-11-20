import { Alert, Button } from 'antd'

interface PageErrorProps {
  message?: string
  onRetry?: () => void
}

export function PageError({ message = '网络连接失败，请检查网络后重试', onRetry }: PageErrorProps) {
  return (
    <Alert
      type="error"
      showIcon
      title={message}
      action={
        onRetry ? (
          <Button size="small" onClick={onRetry}>
            重试
          </Button>
        ) : undefined
      }
    />
  )
}
