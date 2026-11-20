import { useEffect, useMemo, useState } from 'react'
import type { TableProps } from 'antd'
import {
  Alert,
  App as AntApp,
  Button,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { listPriceHistory, listPrices, updatePrice } from '../api/admin'
import { ApiError } from '../api/client'
import type { ModelPrice, PriceHistoryEntry } from '../api/types'
import { PageError } from '../components/PageError'
import { PageHeader } from '../components/PageHeader'
import { formatDateTime } from '../utils/format'

interface ReasonTarget {
  model: string
  draft: ModelPrice
}

function validatePrice(price: ModelPrice): string | null {
  const numericFields: Array<[number, string]> = [
    [price.in_hit_per_m, '命中输入单价'],
    [price.in_miss_per_m, '未命中输入单价'],
    [price.out_per_m, '输出单价'],
  ]
  for (const [value, label] of numericFields) {
    if (!Number.isFinite(value) || !Number.isInteger(value)) {
      return `${label}必须是整数`
    }
    if (value < 0) {
      return `${label}不能为负数`
    }
  }
  if (!Number.isFinite(price.max_tokens_cap) || !Number.isInteger(price.max_tokens_cap)) {
    return 'max_tokens 上限必须是整数'
  }
  if (price.max_tokens_cap < 1) {
    return 'max_tokens 上限必须大于 0'
  }
  return null
}

function isDirty(draft: ModelPrice, row: ModelPrice): boolean {
  return (
    draft.in_hit_per_m !== row.in_hit_per_m ||
    draft.in_miss_per_m !== row.in_miss_per_m ||
    draft.out_per_m !== row.out_per_m ||
    draft.thinking !== row.thinking ||
    draft.max_tokens_cap !== row.max_tokens_cap ||
    draft.enabled !== row.enabled
  )
}

const HISTORY_COLUMNS: TableProps<PriceHistoryEntry>['columns'] = [
  { title: '版本', dataIndex: 'version', width: 70 },
  { title: '命中输入', dataIndex: 'in_hit_per_m', width: 100 },
  { title: '未命中输入', dataIndex: 'in_miss_per_m', width: 110 },
  { title: '输出', dataIndex: 'out_per_m', width: 90 },
  {
    title: '启用',
    dataIndex: 'enabled',
    width: 80,
    render: (value: boolean) => (value ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
  },
  { title: '原因', dataIndex: 'reason', ellipsis: true },
  { title: '管理员', dataIndex: 'admin_id', width: 90 },
  {
    title: '修改时间',
    dataIndex: 'created_at',
    width: 170,
    render: (value: string) => formatDateTime(value),
  },
]

export function PricesPage() {
  const { message } = AntApp.useApp()
  const [rows, setRows] = useState<ModelPrice[]>([])
  const [drafts, setDrafts] = useState<Record<string, ModelPrice>>({})
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [history, setHistory] = useState<Record<string, PriceHistoryEntry[]>>({})
  const [historyLoading, setHistoryLoading] = useState<Record<string, boolean>>({})
  const [reasonTarget, setReasonTarget] = useState<ReasonTarget | null>(null)
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)

  const load = useMemo(
    () => async () => {
      setLoading(true)
      setLoadError(null)
      try {
        const data = await listPrices()
        setRows(data.items ?? [])
        setDrafts({})
      } catch (err) {
        setLoadError(err instanceof ApiError ? err.message : '加载价格失败')
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    void load()
  }, [load])

  function setDraftField<K extends keyof ModelPrice>(
    row: ModelPrice,
    field: K,
    value: ModelPrice[K],
  ): void {
    setDrafts((previous) => ({
      ...previous,
      [row.model]: { ...(previous[row.model] ?? row), [field]: value },
    }))
  }

  const loadHistory = async (model: string) => {
    setHistoryLoading((previous) => ({ ...previous, [model]: true }))
    try {
      const data = await listPriceHistory(model)
      setHistory((previous) => ({ ...previous, [model]: data.items ?? [] }))
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '加载价格历史失败')
    } finally {
      setHistoryLoading((previous) => ({ ...previous, [model]: false }))
    }
  }

  const openReasonModal = (row: ModelPrice) => {
    const draft = drafts[row.model] ?? row
    const invalid = validatePrice(draft)
    if (invalid) {
      setActionError(invalid)
      return
    }
    setActionError(null)
    setReason('')
    setReasonTarget({ model: row.model, draft })
  }

  const handleSave = async () => {
    if (!reasonTarget) return
    const trimmed = reason.trim()
    if (!trimmed) return
    setSaving(true)
    setActionError(null)
    try {
      const updated = await updatePrice(reasonTarget.model, {
        in_hit_per_m: reasonTarget.draft.in_hit_per_m,
        in_miss_per_m: reasonTarget.draft.in_miss_per_m,
        out_per_m: reasonTarget.draft.out_per_m,
        thinking: reasonTarget.draft.thinking,
        max_tokens_cap: reasonTarget.draft.max_tokens_cap,
        enabled: reasonTarget.draft.enabled,
        reason: trimmed,
      })
      setRows((previous) =>
        previous.map((row) =>
          row.model === reasonTarget.model
            ? {
                ...reasonTarget.draft,
                version: updated?.version ?? row.version + 1,
                updated_at: updated?.updated_at ?? row.updated_at,
              }
            : row,
        ),
      )
      setDrafts((previous) => {
        const next = { ...previous }
        delete next[reasonTarget.model]
        return next
      })
      setHistory((previous) => {
        const next = { ...previous }
        delete next[reasonTarget.model]
        return next
      })
      setReasonTarget(null)
      message.success('价格已更新')
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '保存失败，请稍后重试')
      setReasonTarget(null)
    } finally {
      setSaving(false)
    }
  }

  const columns: TableProps<ModelPrice>['columns'] = [
    {
      title: '模型',
      dataIndex: 'model',
      width: 180,
      render: (value: string) => <Typography.Text strong>{value}</Typography.Text>,
    },
    {
      title: '命中输入单价',
      dataIndex: 'in_hit_per_m',
      width: 140,
      render: (_: number, row) => {
        const current = drafts[row.model] ?? row
        return (
          <InputNumber
            precision={0}
            style={{ width: '100%' }}
            value={current.in_hit_per_m}
            onChange={(value) =>
              setDraftField(row, 'in_hit_per_m', typeof value === 'number' ? value : 0)
            }
          />
        )
      },
    },
    {
      title: '未命中输入单价',
      dataIndex: 'in_miss_per_m',
      width: 140,
      render: (_: number, row) => {
        const current = drafts[row.model] ?? row
        return (
          <InputNumber
            precision={0}
            style={{ width: '100%' }}
            value={current.in_miss_per_m}
            onChange={(value) =>
              setDraftField(row, 'in_miss_per_m', typeof value === 'number' ? value : 0)
            }
          />
        )
      },
    },
    {
      title: '输出单价',
      dataIndex: 'out_per_m',
      width: 130,
      render: (_: number, row) => {
        const current = drafts[row.model] ?? row
        return (
          <InputNumber
            precision={0}
            style={{ width: '100%' }}
            value={current.out_per_m}
            onChange={(value) =>
              setDraftField(row, 'out_per_m', typeof value === 'number' ? value : 0)
            }
          />
        )
      },
    },
    {
      title: '思考模式',
      dataIndex: 'thinking',
      width: 120,
      render: (_: string, row) => {
        const current = drafts[row.model] ?? row
        return (
          <Select
            style={{ width: '100%' }}
            value={current.thinking}
            options={[
              { value: 'disabled', label: '关闭' },
              { value: 'enabled', label: '开启' },
            ]}
            onChange={(value) =>
              setDraftField(row, 'thinking', value === 'enabled' ? 'enabled' : 'disabled')
            }
          />
        )
      },
    },
    {
      title: 'max_tokens 上限',
      dataIndex: 'max_tokens_cap',
      width: 130,
      render: (_: number, row) => {
        const current = drafts[row.model] ?? row
        return (
          <InputNumber
            precision={0}
            style={{ width: '100%' }}
            value={current.max_tokens_cap}
            onChange={(value) =>
              setDraftField(row, 'max_tokens_cap', typeof value === 'number' ? value : 0)
            }
          />
        )
      },
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 80,
      render: (_: boolean, row) => {
        const current = drafts[row.model] ?? row
        return (
          <Switch
            checked={current.enabled}
            onChange={(checked) => setDraftField(row, 'enabled', checked)}
          />
        )
      },
    },
    {
      title: '版本',
      dataIndex: 'version',
      width: 70,
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      render: (_: unknown, row) => {
        const dirty = isDirty(drafts[row.model] ?? row, row)
        return (
          <Button type="link" disabled={!dirty} onClick={() => openReasonModal(row)}>
            保存
          </Button>
        )
      },
    },
  ]

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader
        code="M-01"
        title="模型定价"
        tag={
          <Tooltip title="单价单位为积分 / 百万 token，整数。修改后立即生效并记录历史。">
            <Tag color="blue">积分 / 百万 token</Tag>
          </Tooltip>
        }
        description="修改价格、思考模式、max_tokens 上限或启用状态后，点击行内“保存”并填写修改原因，系统会保留版本历史与审计记录。"
      />

      {loadError ? <PageError message={loadError} onRetry={() => void load()} /> : null}
      {actionError ? <Alert type="error" showIcon title={actionError} /> : null}

      <Table<ModelPrice>
        rowKey="model"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 1100 }}
        expandable={{
          expandedRowRender: (row) => (
            <Table<PriceHistoryEntry>
              rowKey={(item) => `${row.model}-${item.version}-${item.id ?? item.created_at}`}
              size="small"
              loading={historyLoading[row.model]}
              columns={HISTORY_COLUMNS}
              dataSource={history[row.model] ?? []}
              pagination={false}
              locale={{ emptyText: '暂无价格历史' }}
            />
          ),
          onExpand: (expanded, row) => {
            if (expanded && !history[row.model]) {
              void loadHistory(row.model)
            }
          },
        }}
      />

      <Modal
        title={reasonTarget ? `保存价格 · ${reasonTarget.model}` : '保存价格'}
        open={reasonTarget !== null}
        confirmLoading={saving}
        okText="确认保存"
        cancelText="取消"
        okButtonProps={{ disabled: reason.trim().length === 0 }}
        onCancel={() => setReasonTarget(null)}
        onOk={() => void handleSave()}
      >
        <Typography.Paragraph type="secondary">
          价格修改会立即生效并写入历史，请填写本次修改原因（必填）。
        </Typography.Paragraph>
        <Input.TextArea
          aria-label="修改原因"
          rows={3}
          value={reason}
          placeholder="例如：按上游成本调整输出单价"
          onChange={(event) => setReason(event.target.value)}
        />
      </Modal>
    </Space>
  )
}
