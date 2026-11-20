import { useCallback, useEffect, useState } from 'react'
import type { TableProps, UploadFile } from 'antd'
import {
  Alert,
  App as AntApp,
  Button,
  Drawer,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Timeline,
  Typography,
  Upload,
} from 'antd'
import {
  deleteReport,
  downloadReport,
  getReport,
  listReports,
  notifyReport,
  replaceReportVersion,
  searchUsers,
  uploadReport,
} from '../api/admin'
import { ApiError } from '../api/client'
import type { ReportDetail, ReportItem, ReportStatus, UserItem } from '../api/types'
import { PageError } from '../components/PageError'
import { PageHeader } from '../components/PageHeader'
import { formatDateTime } from '../utils/format'

const STATUS_META: Record<ReportStatus, { label: string; color: string }> = {
  pending: { label: '未通知', color: 'default' },
  notified: { label: '已通知', color: 'blue' },
  downloaded: { label: '已下载', color: 'green' },
}

function formatSize(bytes: number): string {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

type EditorState = { mode: 'create' } | { mode: 'replace'; report: ReportItem } | null

export function ReportsPage() {
  const { message } = AntApp.useApp()

  const [filters, setFilters] = useState({ phone: '', keyword: '', status: '' })
  const [applied, setApplied] = useState({ phone: '', keyword: '', status: '' })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [reloadKey, setReloadKey] = useState(0)
  const [rows, setRows] = useState<ReportItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [editor, setEditor] = useState<EditorState>(null)
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [phone, setPhone] = useState('')
  const [matchedUsers, setMatchedUsers] = useState<UserItem[]>([])
  const [selectedUserId, setSelectedUserId] = useState<number | undefined>()
  const [title, setTitle] = useState('')
  const [lookupLoading, setLookupLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const [detailId, setDetailId] = useState<number | null>(null)
  const [detail, setDetail] = useState<ReportDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await listReports({
        phone: applied.phone || undefined,
        keyword: applied.keyword || undefined,
        status: applied.status || undefined,
        page,
        page_size: pageSize,
      })
      setRows(data.items ?? [])
      setTotal(data.total ?? 0)
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : '加载检测报告失败')
    } finally {
      setLoading(false)
    }
  }, [applied, page, pageSize, reloadKey])

  useEffect(() => {
    void load()
  }, [load])

  const reload = () => setReloadKey((value) => value + 1)

  const openEditor = (state: Exclude<EditorState, null>) => {
    setEditor(state)
    setFileList([])
    setPhone('')
    setMatchedUsers([])
    setSelectedUserId(undefined)
    setTitle('')
  }

  const lookupUsers = async () => {
    const value = phone.trim()
    if (!value) {
      setMatchedUsers([])
      return
    }
    setLookupLoading(true)
    try {
      const data = await searchUsers(value)
      const items = data.items ?? []
      setMatchedUsers(items)
      if (items.length === 1) {
        setSelectedUserId(items[0].id)
      }
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '查询用户失败')
    } finally {
      setLookupLoading(false)
    }
  }

  const submitEditor = async () => {
    if (!editor) return
    const file = fileList[0]?.originFileObj as File | undefined
    if (!file) {
      message.warning('请选择报告文件')
      return
    }
    setSubmitting(true)
    try {
      if (editor.mode === 'create') {
        if (!selectedUserId) {
          message.warning('请先查询并选择绑定用户')
          return
        }
        await uploadReport({
          userId: selectedUserId,
          phone: phone.trim() || undefined,
          title: title.trim() || file.name,
          file,
        })
        message.success('报告已上传并通知用户')
      } else {
        await replaceReportVersion(editor.report.id, file)
        message.success('已上传新版本并重新通知用户')
      }
      setEditor(null)
      reload()
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  const openDetail = async (id: number) => {
    setDetailId(id)
    setDetail(null)
    setDetailLoading(true)
    try {
      setDetail(await getReport(id))
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '加载报告详情失败')
    } finally {
      setDetailLoading(false)
    }
  }

  const handleDownload = async (record: ReportItem, version?: number) => {
    try {
      await downloadReport(record.id, version, version ? `v${version}-${record.filename}` : record.filename)
      message.success('已开始下载')
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '下载失败')
    }
  }

  const handleNotify = async (record: ReportItem) => {
    try {
      await notifyReport(record.id)
      message.success('已重新通知用户')
      reload()
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '通知失败')
    }
  }

  const handleDelete = async (record: ReportItem) => {
    try {
      await deleteReport(record.id)
      message.success('报告已删除')
      reload()
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  const columns: TableProps<ReportItem>['columns'] = [
    { title: '手机号', dataIndex: 'phone_mask', width: 140 },
    { title: '报告标题', dataIndex: 'title', ellipsis: true },
    { title: '文件名', dataIndex: 'filename', ellipsis: true },
    { title: '版本', dataIndex: 'version', width: 70, render: (v: number) => `v${v}` },
    {
      title: '大小',
      dataIndex: 'size_bytes',
      width: 100,
      render: (value: number) => formatSize(value),
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      width: 170,
      render: (value: string) => formatDateTime(value),
    },
    {
      title: '投递状态',
      key: 'status',
      width: 100,
      render: (_: unknown, record) => {
        if (record.read_at) {
          return <Tag color="gold">已读</Tag>
        }
        const meta = STATUS_META[record.status] ?? STATUS_META.pending
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 280,
      render: (_: unknown, record) => (
        <Space size={4} wrap>
          <Button type="link" size="small" onClick={() => void openDetail(record.id)}>
            详情
          </Button>
          <Button type="link" size="small" onClick={() => void handleDownload(record)}>
            下载
          </Button>
          <Button type="link" size="small" onClick={() => openEditor({ mode: 'replace', report: record })}>
            替换
          </Button>
          <Button type="link" size="small" onClick={() => void handleNotify(record)}>
            通知
          </Button>
          <Popconfirm
            title="删除该报告？"
            description="删除后用户端不再出现该报告，已下载到本地的副本不受影响。"
            okText="删除"
            cancelText="取消"
            onConfirm={() => void handleDelete(record)}
          >
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const versionColumns: TableProps<ReportDetail['versions'][number]>['columns'] = [
    { title: '版本', dataIndex: 'version', width: 70, render: (v: number) => `v${v}` },
    { title: '文件名', dataIndex: 'filename', ellipsis: true },
    {
      title: '大小',
      dataIndex: 'size_bytes',
      width: 100,
      render: (value: number) => formatSize(value),
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      width: 170,
      render: (value: string) => formatDateTime(value),
    },
    {
      title: '操作',
      key: 'actions',
      width: 90,
      render: (_: unknown, record) => (
        <Button
          type="link"
          size="small"
          onClick={() => {
            if (detail) {
              void handleDownload(detail, record.version)
            }
          }}
        >
          下载
        </Button>
      ),
    },
  ]

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader
        code="M-08"
        title="检测报告"
        description="上传并投递基因与心理检测报告，按手机号核对接收人、版本与发送状态。"
        actions={
          <Space>
            <Button onClick={reload} loading={loading}>
              刷新
            </Button>
            <Button type="primary" onClick={() => openEditor({ mode: 'create' })}>
              上传报告
            </Button>
          </Space>
        }
      />

      <Alert
        type="info"
        showIcon
        title="报告仅投递给绑定的主账号。用户在线时立即收到提醒，离线则在下次上线后补发。"
      />

      <Space wrap>
        <Input
          style={{ width: 180 }}
          placeholder="手机号"
          value={filters.phone}
          onChange={(event) => setFilters((prev) => ({ ...prev, phone: event.target.value }))}
          onPressEnter={() => {
            setApplied(filters)
            setPage(1)
            reload()
          }}
        />
        <Input
          style={{ width: 220 }}
          placeholder="标题或文件名关键词"
          value={filters.keyword}
          onChange={(event) => setFilters((prev) => ({ ...prev, keyword: event.target.value }))}
          onPressEnter={() => {
            setApplied(filters)
            setPage(1)
            reload()
          }}
        />
        <Select
          style={{ width: 140 }}
          placeholder="投递状态"
          allowClear
          value={filters.status || undefined}
          onChange={(value) => setFilters((prev) => ({ ...prev, status: value ?? '' }))}
          options={[
            { value: 'pending', label: '未通知' },
            { value: 'notified', label: '已通知' },
            { value: 'downloaded', label: '已下载' },
          ]}
        />
        <Button
          type="primary"
          onClick={() => {
            setApplied(filters)
            setPage(1)
            reload()
          }}
        >
          查询
        </Button>
        <Button
          onClick={() => {
            const empty = { phone: '', keyword: '', status: '' }
            setFilters(empty)
            setApplied(empty)
            setPage(1)
            reload()
          }}
        >
          重置
        </Button>
      </Space>

      {loadError ? <PageError message={loadError} onRetry={() => void load()} /> : null}

      <Table<ReportItem>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (value) => `共 ${value} 份报告`,
          onChange: (nextPage, nextSize) => {
            setPage(nextPage)
            setPageSize(nextSize)
          },
        }}
        locale={{ emptyText: '暂无检测报告' }}
        scroll={{ x: 1180 }}
      />

      <Modal
        open={editor !== null}
        title={editor?.mode === 'replace' ? '替换报告文件' : '上传检测报告'}
        okText={editor?.mode === 'replace' ? '上传新版本' : '上传并通知'}
        cancelText="取消"
        confirmLoading={submitting}
        onOk={() => void submitEditor()}
        onCancel={() => setEditor(null)}
        destroyOnHidden
      >
        <Space orientation="vertical" size={12} style={{ width: '100%' }}>
          {editor?.mode === 'replace' ? (
            <Alert
              type="warning"
              showIcon
              title={`替换后生成新版本，并重新通知用户（当前 v${editor.report.version}）。历史版本文件保留。`}
            />
          ) : (
            <>
              <Typography.Text>绑定用户</Typography.Text>
              <Space.Compact style={{ width: '100%' }}>
                <Input
                  placeholder="输入完整手机号"
                  value={phone}
                  onChange={(event) => setPhone(event.target.value)}
                  onBlur={() => void lookupUsers()}
                />
                <Button loading={lookupLoading} onClick={() => void lookupUsers()}>
                  查询
                </Button>
              </Space.Compact>
              <Select
                style={{ width: '100%' }}
                placeholder="选择用户"
                value={selectedUserId}
                onChange={(value) => setSelectedUserId(value)}
                notFoundContent="未匹配到用户"
                options={matchedUsers.map((user) => ({
                  value: user.id,
                  label: `${user.phone_mask}（ID ${user.id}，可用 ${user.balance - user.held}）`,
                }))}
              />
              <Typography.Text>报告标题</Typography.Text>
              <Input
                placeholder="留空则使用文件名"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            </>
          )}

          <Upload.Dragger
            multiple={false}
            maxCount={1}
            fileList={fileList}
            beforeUpload={() => false}
            onChange={({ fileList: next }) => setFileList(next.slice(-1))}
            accept=".pdf,.png,.jpg,.jpeg,.webp,.doc,.docx"
          >
            <p style={{ margin: 0 }}>点击或拖拽文件到此处</p>
            <p style={{ margin: 0, color: '#999' }}>
              支持 PDF / 图片 / Word，单个文件不超过 20MB
            </p>
          </Upload.Dragger>
        </Space>
      </Modal>

      <Drawer
        title={detail ? `报告 #${detail.id} · ${detail.title}` : '报告详情'}
        width="large"
        open={detailId !== null}
        loading={detailLoading}
        onClose={() => setDetailId(null)}
        extra={
          detail ? (
            <Space>
              <Tag>{detail.phone_mask}</Tag>
              <Tag color="blue">v{detail.version}</Tag>
            </Space>
          ) : null
        }
      >
        {detail ? (
          <Space orientation="vertical" size={16} style={{ width: '100%' }}>
            <Timeline
              items={[
                {
                  color: 'blue',
                  children: `上传：${formatDateTime(detail.created_at)}`,
                },
                {
                  color: detail.notified_at ? 'blue' : 'gray',
                  children: `通知用户：${formatDateTime(detail.notified_at)}`,
                },
                {
                  color: detail.downloaded_at ? 'green' : 'gray',
                  children: `用户下载：${formatDateTime(detail.downloaded_at)}`,
                },
                {
                  color: detail.read_at ? 'gold' : 'gray',
                  children: `用户已读：${formatDateTime(detail.read_at)}`,
                },
              ]}
            />
            <Table
              rowKey="version"
              size="small"
              columns={versionColumns}
              dataSource={detail.versions}
              pagination={false}
            />
          </Space>
        ) : null}
      </Drawer>
    </Space>
  )
}
