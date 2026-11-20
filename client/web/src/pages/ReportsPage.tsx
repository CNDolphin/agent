import { Alert, Badge, Button, Card, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useState } from 'react'

import { api, downloadFile, errorMessage } from '../api'
import type { ReportItem, ReportList, ReportReadResult, ReportSyncResult } from '../types'

/** 报告状态变化后,通知侧边栏刷新未读角标。 */
export const REPORTS_UPDATED_EVENT = 'mhagent:reports-updated'

export function notifyReportsUpdated() {
  window.dispatchEvent(new Event(REPORTS_UPDATED_EVENT))
}

function formatSize(size: number): string {
  if (!size) return '-'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function formatTime(value: string): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function ReportsPage() {
  const [items, setItems] = useState<ReportItem[]>([])
  const [unread, setUnread] = useState(0)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState('')
  const [messageApi, holder] = message.useMessage()

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await api.get<ReportList>('/reports')
      setItems(data.items)
      setUnread(data.unread)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function sync() {
    setSyncing(true)
    setError('')
    try {
      const data = await api.post<ReportSyncResult>('/reports/sync')
      setItems(data.items)
      setUnread(data.unread)
      notifyReportsUpdated()
      if (data.synced > 0) {
        messageApi.success(`已下载 ${data.synced} 份新报告`)
      } else {
        messageApi.info('暂时没有新的报告')
      }
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSyncing(false)
    }
  }

  async function openFile(item: ReportItem) {
    setError('')
    try {
      await downloadFile(`/reports/${item.report_id}/file`, item.filename)
      if (!item.read_at) {
        await markRead(item, true)
      }
      messageApi.success(`已保存到本机下载目录:${item.filename}`)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function markRead(item: ReportItem, silent = false) {
    try {
      const data = await api.post<ReportReadResult>(`/reports/${item.report_id}/read`)
      setItems((current) =>
        current.map((report) =>
          report.report_id === data.item.report_id ? data.item : report,
        ),
      )
      setUnread(data.unread)
      notifyReportsUpdated()
      if (!silent) messageApi.success('已标记为已读')
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const columns: ColumnsType<ReportItem> = [
    {
      title: '报告',
      dataIndex: 'title',
      key: 'title',
      width: 240,
      render: (_, item) => (
        <Space direction="vertical" size={0} style={{ width: '100%', maxWidth: '100%' }}>
          <Typography.Text strong ellipsis={{ tooltip: item.title }}>
            {item.title}
          </Typography.Text>
          <Typography.Text
            type="secondary"
            ellipsis={{ tooltip: `${item.filename} · v${item.version}` }}
            style={{ fontSize: 12, maxWidth: '100%' }}
          >
            {item.filename} · v{item.version}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '文件路径',
      dataIndex: 'abs_path',
      key: 'abs_path',
      width: 300,
      render: (value: string) =>
        value ? (
          <Typography.Text
            copyable={{ text: value }}
            ellipsis={{ tooltip: value }}
            style={{ display: 'block', maxWidth: 270, fontSize: 12 }}
          >
            {value}
          </Typography.Text>
        ) : (
          '-'
        ),
    },
    {
      title: '大小',
      dataIndex: 'size_bytes',
      key: 'size_bytes',
      width: 100,
      render: (value: number) => formatSize(value),
    },
    {
      title: '收到时间',
      dataIndex: 'downloaded_at',
      key: 'downloaded_at',
      width: 180,
      render: (value: string) => formatTime(value),
    },
    {
      title: '状态',
      key: 'state',
      width: 90,
      render: (_, item) =>
        item.read_at ? <Tag>已读</Tag> : <Tag color="red">未读</Tag>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 190,
      render: (_, item) => (
        <Space>
          <Button type="link" size="small" onClick={() => void openFile(item)}>
            打开文件
          </Button>
          {!item.read_at && (
            <Button type="link" size="small" onClick={() => void markRead(item)}>
              标记已读
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div className="page-stack">
      {holder}
      <Space style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap' }}>
        <Space direction="vertical" size={0}>
          <Space align="center">
            <Typography.Title level={4} style={{ margin: 0 }}>
              我的报告
            </Typography.Title>
            {unread > 0 && <Badge count={unread} />}
          </Space>
          <Typography.Text type="secondary">
            检测报告会自动下载到本机文档目录(documents),只保存在这台设备上;主账号可见全部,子账号仅显示标题或文件名包含本人昵称的报告。
          </Typography.Text>
        </Space>
        <Space>
          <Button onClick={() => void load()} loading={loading}>
            刷新
          </Button>
          <Button type="primary" onClick={() => void sync()} loading={syncing}>
            检查新报告
          </Button>
        </Space>
      </Space>

      {error && <Alert type="error" showIcon message={error} />}

      <Card>
        <Table<ReportItem>
          rowKey="report_id"
          columns={columns}
          dataSource={items}
          loading={loading}
          pagination={false}
          tableLayout="fixed"
          scroll={{ x: 1100 }}
          locale={{ emptyText: '暂无检测报告' }}
        />
      </Card>
    </div>
  )
}
