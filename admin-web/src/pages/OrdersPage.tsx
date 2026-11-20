import { useCallback, useEffect, useState } from 'react'
import type { TableProps } from 'antd'
import {
  Alert,
  App as AntApp,
  Button,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { cancelOrder, confirmOrder, listOrders } from '../api/admin'
import { ApiError } from '../api/client'
import type { OrderItem } from '../api/types'
import { useSessionRole } from '../api/session'
import { PageError } from '../components/PageError'
import { PageHeader } from '../components/PageHeader'
import { formatDateTime, formatMoney, ORDER_STATUS_COLORS, ORDER_STATUS_LABELS } from '../utils/format'

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '待支付' },
  { value: 'paid', label: '已支付待入账' },
  { value: 'credited', label: '已入账' },
  { value: 'cancelled', label: '已取消' },
]

export function OrdersPage() {
  const { message, modal } = AntApp.useApp()
  const role = useSessionRole()
  const [rows, setRows] = useState<OrderItem[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState('')
  const [phoneInput, setPhoneInput] = useState('')

  const load = useCallback(async (status: string, phone: string) => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await listOrders({
        status: status || undefined,
        phone: phone.trim() || undefined,
      })
      setRows(data.items ?? [])
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : '加载订单失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load('', '')
  }, [load])

  const handleSearch = () => {
    void load(statusFilter, phoneInput)
  }

  const handleConfirm = (record: OrderItem) => {
    modal.confirm({
      title: '确认收款',
      content: `确认已收到订单 #${record.id}（${record.package_name}）的线下款项？确认后将立即为该用户入账 ${record.credits} 积分，且不可撤销。`,
      okText: '确认收款',
      cancelText: '取消',
      onOk: async () => {
        try {
          await confirmOrder(record.id)
          message.success('已确认收款，积分已入账')
          await load(statusFilter, phoneInput)
        } catch (err) {
          message.error(err instanceof ApiError ? err.message : '确认收款失败')
        }
      },
    })
  }

  const handleCancel = (record: OrderItem) => {
    modal.confirm({
      title: '取消订单',
      content: `确认取消订单 #${record.id}？取消后订单不可恢复，也不会入账积分。`,
      okText: '确认取消',
      cancelText: '返回',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await cancelOrder(record.id)
          message.success('订单已取消')
          await load(statusFilter, phoneInput)
        } catch (err) {
          message.error(err instanceof ApiError ? err.message : '取消订单失败')
        }
      },
    })
  }

  const columns: TableProps<OrderItem>['columns'] = [
    { title: '订单号', dataIndex: 'id', width: 90 },
    { title: '用户 ID', dataIndex: 'user_id', width: 100 },
    {
      title: '手机号',
      dataIndex: 'phone_mask',
      width: 140,
      render: (value?: string) => value ?? '-',
    },
    { title: '套餐', dataIndex: 'package_name', width: 160 },
    {
      title: '金额',
      dataIndex: 'price_cents',
      width: 100,
      render: (value: number) => formatMoney(value),
    },
    { title: '积分', dataIndex: 'credits', width: 80 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 130,
      render: (value: string) => (
        <Tag color={ORDER_STATUS_COLORS[value]}>{ORDER_STATUS_LABELS[value] ?? value}</Tag>
      ),
    },
    { title: '渠道', dataIndex: 'channel', width: 100 },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (value: string) => formatDateTime(value),
    },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      render: (_: unknown, record) => {
        const canOperate =
          role === 'super' && record.channel === 'manual' && record.status === 'pending'
        if (!canOperate) {
          return <Typography.Text type="secondary">-</Typography.Text>
        }
        return (
          <Space size={4}>
            <Button type="link" onClick={() => handleConfirm(record)}>
              确认收款
            </Button>
            <Button type="link" danger onClick={() => handleCancel(record)}>
              取消
            </Button>
          </Space>
        )
      },
    },
  ]

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader
        code="M-03"
        title="订单管理"
        description="按状态与手机号尾号检索支付订单，核对金额、到账积分与渠道流水号。"
      />

      <Space wrap>
        <Select
          style={{ width: 170 }}
          value={statusFilter}
          options={STATUS_OPTIONS}
          onChange={(value) => setStatusFilter(value)}
        />
        <Input
          style={{ width: 200 }}
          placeholder="手机号尾号"
          value={phoneInput}
          onChange={(event) => setPhoneInput(event.target.value)}
          onPressEnter={handleSearch}
        />
        <Button type="primary" onClick={handleSearch}>
          查询
        </Button>
      </Space>

      {loadError ? <PageError message={loadError} onRetry={() => void load(statusFilter, phoneInput)} /> : null}

      <Alert
        type="info"
        showIcon
        title="仅 manual 渠道的待支付订单支持后台确认收款；确认后积分立即入账，已入账订单不可再操作。"
      />

      <Table<OrderItem>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 1100 }}
        locale={{ emptyText: '暂无订单' }}
      />
    </Space>
  )
}
