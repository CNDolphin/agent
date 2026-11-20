import { useCallback, useEffect, useState } from 'react'
import type { TableProps } from 'antd'
import { Alert, Button, Space, Table, Tag } from 'antd'
import { listNotifyLogs } from '../api/admin'
import { ApiError } from '../api/client'
import type { NotifyLogItem } from '../api/types'
import { PageError } from '../components/PageError'
import { PageHeader } from '../components/PageHeader'
import {
  formatDateTime,
  NOTIFY_CHANNEL_LABELS,
  NOTIFY_STATUS_LABELS,
} from '../utils/format'

export function NotifyLogsPage() {
  const [rows, setRows] = useState<NotifyLogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await listNotifyLogs()
      setRows(data.items ?? [])
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : '加载通知记录失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const columns: TableProps<NotifyLogItem>['columns'] = [
    { title: 'ID', dataIndex: 'id', width: 90 },
    { title: '用户 ID', dataIndex: 'user_id', width: 110 },
    {
      title: '渠道',
      dataIndex: 'channel',
      width: 100,
      render: (value: string) => (
        <Tag color={value === 'sms' ? 'blue' : 'purple'}>
          {NOTIFY_CHANNEL_LABELS[value] ?? value}
        </Tag>
      ),
    },
    { title: '模板', dataIndex: 'template_id', width: 220 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 120,
      render: (value: string) => (
        <Tag color={value === 'sent' ? 'green' : 'red'}>
          {NOTIFY_STATUS_LABELS[value] ?? value}
        </Tag>
      ),
    },
    {
      title: '发送时间',
      dataIndex: 'created_at',
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
  ]

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader
        code="M-06"
        title="通知记录"
        description="核对紧急通知的渠道、模板与发送状态，用于事后追溯。"
        actions={
          <Button onClick={() => void load()} loading={loading}>
            刷新
          </Button>
        }
      />

      <Alert
        type="info"
        showIcon
        title="紧急通知记录仅保留渠道、模板与发送状态，不保存收件人与通知参数，也不包含任何对话内容。"
      />

      {loadError ? <PageError message={loadError} onRetry={() => void load()} /> : null}

      <Table<NotifyLogItem>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: '暂无通知记录' }}
      />
    </Space>
  )
}
