import { useCallback, useEffect, useState } from 'react'
import type { TableProps, UploadFile } from 'antd'
import {
  Alert,
  App as AntApp,
  Button,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd'
import {
  downloadContent,
  listContents,
  notifyContent,
  offlineContent,
  uploadContent,
} from '../api/admin'
import type { ContentItem, ContentKind } from '../api/admin'
import { ApiError } from '../api/client'
import { PageError } from '../components/PageError'
import { PageHeader } from '../components/PageHeader'
import { formatDateTime } from '../utils/format'

const KIND_META: Record<ContentKind, { label: string; color: string }> = {
  skills: { label: '技能包', color: 'geekblue' },
  quiz: { label: '测评题库', color: 'purple' },
  rules: { label: '风险规则', color: 'volcano' },
  scales: { label: '量表/练习', color: 'cyan' },
  app: { label: '客户端程序', color: 'gold' },
}

const KIND_OPTIONS = (Object.keys(KIND_META) as ContentKind[]).map((value) => ({
  value,
  label: KIND_META[value].label,
}))

function formatSize(bytes: number): string {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function ContentPage() {
  const { message } = AntApp.useApp()

  const [kindFilter, setKindFilter] = useState<string>('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [reloadKey, setReloadKey] = useState(0)
  const [rows, setRows] = useState<ContentItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [editorOpen, setEditorOpen] = useState(false)
  const [kind, setKind] = useState<ContentKind>('skills')
  const [version, setVersion] = useState('')
  const [platform, setPlatform] = useState('windows')
  const [notes, setNotes] = useState('')
  const [forced, setForced] = useState(false)
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [downloadingId, setDownloadingId] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await listContents({
        kind: kindFilter || undefined,
        page,
        page_size: pageSize,
      })
      setRows(data.items ?? [])
      setTotal(data.total ?? 0)
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : '加载内容版本失败')
    } finally {
      setLoading(false)
    }
  }, [kindFilter, page, pageSize, reloadKey])

  useEffect(() => {
    void load()
  }, [load])

  const reload = () => setReloadKey((value) => value + 1)

  const windowsApp = kind === 'app' && platform === 'windows'

  const openEditor = () => {
    setKind('skills')
    setVersion('')
    setPlatform('windows')
    setNotes('')
    setForced(false)
    setFileList([])
    setEditorOpen(true)
  }

  const submit = async () => {
    const file = fileList[0]?.originFileObj as File | undefined
    if (!file) {
      message.warning(windowsApp ? '请选择 exe 安装包' : '请选择内容包 zip 文件')
      return
    }
    if (windowsApp) {
      if (!file.name.toLowerCase().endsWith('.exe')) {
        message.warning('Windows 客户端程序需上传 .exe 安装包')
        return
      }
    } else if (!file.name.toLowerCase().endsWith('.zip')) {
      message.warning('请上传 zip 内容包')
      return
    }
    if (!/^\d+\.\d+\.\d+$/.test(version.trim())) {
      message.warning('版本号需为 x.y.z 格式，例如 1.0.1')
      return
    }
    setSubmitting(true)
    try {
      await uploadContent({
        kind,
        version: version.trim(),
        platform: kind === 'app' ? platform : undefined,
        notes: notes.trim() || undefined,
        forced,
        file,
      })
      message.success('已发布，并向在线客户端推送更新通知')
      setEditorOpen(false)
      reload()
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '发布失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleNotify = async (record: ContentItem) => {
    try {
      await notifyContent(record.id)
      message.success('已重新通知在线客户端')
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '通知失败')
    }
  }

  const handleOffline = async (record: ContentItem) => {
    try {
      await offlineContent(record.id)
      message.success('版本已下线，客户端将不再提示该版本')
      reload()
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '下线失败')
    }
  }

  const handleDownload = async (record: ContentItem) => {
    if (downloadingId !== null) return
    setDownloadingId(record.id)
    const hideLoading = message.loading(`正在下载 ${record.filename}…`, 0)
    try {
      await downloadContent(record.id, record.filename)
      message.success('已开始下载,请在浏览器下载记录中查看')
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '下载失败')
    } finally {
      hideLoading()
      setDownloadingId(null)
    }
  }

  const columns: TableProps<ContentItem>['columns'] = [
    {
      title: '类型',
      dataIndex: 'kind',
      width: 120,
      render: (value: ContentKind) => {
        const meta = KIND_META[value] ?? { label: value, color: 'default' }
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    { title: '版本', dataIndex: 'version', width: 90, render: (v: string) => `v${v}` },
    { title: '平台', dataIndex: 'platform', width: 90 },
    { title: '文件名', dataIndex: 'filename', ellipsis: true },
    {
      title: '大小',
      dataIndex: 'size_bytes',
      width: 100,
      render: (value: number) => formatSize(value),
    },
    {
      title: 'SHA256',
      dataIndex: 'sha256',
      width: 110,
      render: (value: string) => <Typography.Text code>{value.slice(0, 8)}</Typography.Text>,
    },
    {
      title: '发布状态',
      dataIndex: 'status',
      width: 100,
      render: (value: string) =>
        value === 'published' ? <Tag color="green">已发布</Tag> : <Tag>已下线</Tag>,
    },
    {
      title: '发布时间',
      dataIndex: 'published_at',
      width: 170,
      render: (value: string | null) => (value ? formatDateTime(value) : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_: unknown, record) => (
        <Space size={4} wrap>
          <Button
            type="link"
            size="small"
            loading={downloadingId === record.id}
            disabled={downloadingId !== null && downloadingId !== record.id}
            onClick={() => void handleDownload(record)}
          >
            下载
          </Button>
          <Button
            type="link"
            size="small"
            disabled={record.status !== 'published'}
            onClick={() => void handleNotify(record)}
          >
            重发通知
          </Button>
          <Popconfirm
            title="下线该版本？"
            description="下线后客户端不再提示，但已下载到本地的内容不受影响。"
            okText="下线"
            cancelText="取消"
            onConfirm={() => void handleOffline(record)}
          >
            <Button type="link" size="small" danger disabled={record.status !== 'published'}>
              下线
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader
        code="M-09"
        title="内容更新"
        description="发布技能、题库、风险规则、量表与客户端程序版本，在线 Agent 会收到更新提醒并由用户手动更新。"
        actions={
          <Space>
            <Button onClick={reload} loading={loading}>
              刷新
            </Button>
            <Button type="primary" onClick={openEditor}>
              发布内容包
            </Button>
          </Space>
        }
      />

      <Alert
        type="info"
        showIcon
        title="内容包需为 zip，根目录包含 manifest.json（kind、version、files[].path/sha256）；Windows 客户端程序上传 .exe（≤200MB），macOS 程序包仍为 zip。客户端仅提示更新，由用户手动确认下载。"
      />

      <Space wrap>
        <Select
          style={{ width: 160 }}
          placeholder="内容类型"
          allowClear
          value={kindFilter || undefined}
          onChange={(value) => {
            setKindFilter(value ?? '')
            setPage(1)
          }}
          options={KIND_OPTIONS}
        />
        <Button
          onClick={() => {
            setKindFilter('')
            setPage(1)
            reload()
          }}
        >
          重置
        </Button>
      </Space>

      {loadError ? <PageError message={loadError} onRetry={() => void load()} /> : null}

      <Table<ContentItem>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (value) => `共 ${value} 个版本`,
          onChange: (nextPage, nextSize) => {
            setPage(nextPage)
            setPageSize(nextSize)
          },
        }}
        locale={{ emptyText: '暂无内容版本' }}
        scroll={{ x: 1180 }}
      />

      <Modal
        open={editorOpen}
        title="发布内容包"
        okText="发布并通知"
        cancelText="取消"
        confirmLoading={submitting}
        onOk={() => void submit()}
        onCancel={() => setEditorOpen(false)}
        destroyOnHidden
      >
        <Space orientation="vertical" size={12} style={{ width: '100%' }}>
          <Typography.Text>内容类型</Typography.Text>
          <Select
            style={{ width: '100%' }}
            value={kind}
            onChange={(value) => {
              setKind(value)
              setFileList([])
              if (value === 'app' && platform !== 'macos') setPlatform('windows')
            }}
            options={KIND_OPTIONS}
          />
          <Typography.Text>版本号</Typography.Text>
          <Input
            placeholder="如 1.0.1"
            value={version}
            onChange={(event) => setVersion(event.target.value)}
          />
          {kind === 'app' ? (
            <>
              <Typography.Text>平台</Typography.Text>
              <Select
                style={{ width: '100%' }}
                value={platform}
                onChange={(value) => {
                  setPlatform(value)
                  setFileList([])
                }}
                options={[
                  { value: 'windows', label: 'Windows' },
                  { value: 'macos', label: 'macOS' },
                ]}
              />
            </>
          ) : null}
          <Typography.Text>变更说明</Typography.Text>
          <Input.TextArea
            rows={2}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="会展示在客户端更新提示中"
          />
          <Space>
            <Switch checked={forced} onChange={setForced} />
            <Typography.Text>标记为重要更新</Typography.Text>
          </Space>
          <Upload.Dragger
            multiple={false}
            maxCount={1}
            fileList={fileList}
            beforeUpload={() => false}
            onChange={({ fileList: next }) => setFileList(next.slice(-1))}
            accept={windowsApp ? '.exe' : '.zip'}
          >
            <p style={{ margin: 0 }}>
              {windowsApp ? '点击或拖拽 exe 到此处' : '点击或拖拽 zip 到此处'}
            </p>
            <p style={{ margin: 0, color: '#999' }}>
              {windowsApp ? 'Windows 客户端程序不超过 200MB' : '内容包不超过 50MB'}
            </p>
          </Upload.Dragger>
        </Space>
      </Modal>
    </Space>
  )
}
