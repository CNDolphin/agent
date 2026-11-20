import { useMemo, useState } from 'react'
import type { TableProps } from 'antd'
import {
  Alert,
  Button,
  Drawer,
  Input,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { listUserLedger, searchUsers } from '../api/admin'
import { ApiError } from '../api/client'
import type { LedgerItem, UserItem } from '../api/types'
import { PageError } from '../components/PageError'
import { PageHeader } from '../components/PageHeader'
import { formatDateTime, LEDGER_TYPE_LABELS } from '../utils/format'

const LEDGER_COLUMNS: TableProps<LedgerItem>['columns'] = [
  {
    title: '时间',
    dataIndex: 'created_at',
    width: 170,
    render: (value: string) => formatDateTime(value),
  },
  {
    title: '类型',
    dataIndex: 'type',
    width: 120,
    render: (value: string) => LEDGER_TYPE_LABELS[value] ?? value,
  },
  { title: '变动积分', dataIndex: 'amount', width: 100 },
  { title: '变动后余额', dataIndex: 'balance_after', width: 110 },
  { title: '变动后冻结', dataIndex: 'held_after', width: 110 },
  {
    title: '备注',
    dataIndex: 'ref',
    render: (value: string | null | undefined, row: LedgerItem) =>
      value ?? row.request_id ?? '-',
  },
]

export function UsersPage() {
  const [keyword, setKeyword] = useState('')
  const [users, setUsers] = useState<UserItem[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [hasSearched, setHasSearched] = useState(false)

  const [activeUser, setActiveUser] = useState<UserItem | null>(null)
  const [ledger, setLedger] = useState<LedgerItem[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [ledgerLoading, setLedgerLoading] = useState(false)
  const [ledgerError, setLedgerError] = useState<string | null>(null)

  const search = useMemo(
    () => async () => {
      setLoading(true)
      setLoadError(null)
      try {
        const data = await searchUsers(keyword.trim())
        setUsers(data.items ?? [])
        setHasSearched(true)
      } catch (err) {
        setLoadError(err instanceof ApiError ? err.message : '查询用户失败')
      } finally {
        setLoading(false)
      }
    },
    [keyword],
  )

  const fetchLedger = async (userId: number, cursor?: string) => {
    setLedgerLoading(true)
    setLedgerError(null)
    try {
      const data = await listUserLedger(userId, { cursor, limit: 20 })
      setLedger((previous) => (cursor ? [...previous, ...(data.items ?? [])] : data.items ?? []))
      setNextCursor(data.next_cursor ?? null)
    } catch (err) {
      setLedgerError(err instanceof ApiError ? err.message : '加载流水失败')
    } finally {
      setLedgerLoading(false)
    }
  }

  const openLedger = (user: UserItem) => {
    setActiveUser(user)
    setLedger([])
    setNextCursor(null)
    void fetchLedger(user.id)
  }

  const columns: TableProps<UserItem>['columns'] = [
    { title: '用户 ID', dataIndex: 'id', width: 100 },
    { title: '手机号（脱敏）', dataIndex: 'phone_mask', width: 160 },
    { title: '余额', dataIndex: 'balance', width: 100 },
    { title: '冻结', dataIndex: 'held', width: 100 },
    {
      title: '可用',
      key: 'available',
      width: 100,
      render: (_: unknown, record) => record.balance - record.held,
    },
    {
      title: '注册时间',
      dataIndex: 'created_at',
      width: 170,
      render: (value?: string) => formatDateTime(value),
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_: unknown, record) => (
        <Button type="link" onClick={() => openLedger(record)}>
          查看流水
        </Button>
      ),
    },
  ]

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader
        code="M-04"
        title="用户查询"
        description="按完整手机号定位用户，查看积分余额、累计用量与最近登录时间。"
      />

      <Space wrap>
        <Input
          style={{ width: 240 }}
          placeholder="输入完整手机号查询"
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          onPressEnter={() => void search()}
        />
        <Button type="primary" loading={loading} onClick={() => void search()}>
          搜索
        </Button>
      </Space>

      <Alert
        type="info"
        showIcon
        title="出于隐私保护，用户列表只显示脱敏手机号（如 138****1234），系统不保存手机号明文。"
      />

      {loadError ? <PageError message={loadError} onRetry={() => void search()} /> : null}

      <Table<UserItem>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={users}
        pagination={false}
        locale={{ emptyText: hasSearched ? '未找到匹配用户' : '请输入手机号后搜索' }}
      />

      <Drawer
        title={
          activeUser
            ? `用户 #${activeUser.id} · ${activeUser.phone_mask} 积分流水`
            : '积分流水'
        }
        width={760}
        open={activeUser !== null}
        onClose={() => setActiveUser(null)}
        extra={
          activeUser ? (
            <Space>
              <Tag>余额 {activeUser.balance}</Tag>
              <Tag>冻结 {activeUser.held}</Tag>
            </Space>
          ) : null
        }
      >
        {ledgerError ? (
          <Alert
            type="error"
            showIcon
            title={ledgerError}
            style={{ marginBottom: 16 }}
            action={
              activeUser ? (
                <Button
                  size="small"
                  onClick={() => void fetchLedger(activeUser.id)}
                >
                  重试
                </Button>
              ) : null
            }
          />
        ) : null}
        <Table<LedgerItem>
          rowKey="id"
          size="small"
          loading={ledgerLoading}
          columns={LEDGER_COLUMNS}
          dataSource={ledger}
          pagination={false}
          locale={{ emptyText: '暂无流水' }}
        />
        {nextCursor ? (
          <div style={{ marginTop: 16, textAlign: 'center' }}>
            <Button
              onClick={() => {
                if (activeUser) {
                  void fetchLedger(activeUser.id, nextCursor ?? undefined)
                }
              }}
            >
              加载更多
            </Button>
          </div>
        ) : null}
        <Typography.Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 0 }}>
          流水只记录积分变动数值，不包含任何对话内容或联系人信息。
        </Typography.Paragraph>
      </Drawer>
    </Space>
  )
}
