import { Alert, Button, Card, Space, Statistic, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { api, errorMessage } from '../api'
import { useStatus } from '../status'
import type { CreditBalance, OrderItem, PackageItem } from '../types'

const STATUS_TEXT: Record<string, string> = {
  pending: '待支付',
  paid: '已支付',
  cancelled: '已取消',
  failed: '支付失败',
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'orange',
  paid: 'green',
  cancelled: 'default',
  failed: 'red',
}

function yuan(cents: number): string {
  return `¥${(cents / 100).toFixed(2)}`
}

export function CreditsPage() {
  const { status } = useStatus()
  const [balance, setBalance] = useState<CreditBalance | null>(null)
  const [packages, setPackages] = useState<PackageItem[]>([])
  const [orders, setOrders] = useState<OrderItem[]>([])
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    try {
      const [credit, packageData, orderData] = await Promise.all([
        api.get<CreditBalance>('/credits'),
        api.get<{ items: PackageItem[] }>('/packages'),
        api.get<{ items: OrderItem[] }>('/orders'),
      ])
      setBalance(credit)
      setPackages(packageData.items)
      setOrders(orderData.items)
      setError('')
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function buy(pkg: PackageItem, channel: 'mock' | 'manual') {
    setLoading(true)
    setError('')
    setNotice('')
    try {
      const order = await api.post<{ order_id: number }>('/orders', {
        package_id: pkg.id,
        channel,
      })
      setNotice(
        channel === 'manual'
          ? `订单 #${order.order_id} 已创建,请等待管理员确认到账。`
          : `订单 #${order.order_id} 已创建,可点击「模拟支付」完成支付。`,
      )
      await load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function mockPay(orderId: number) {
    setLoading(true)
    setError('')
    try {
      await api.post(`/orders/${orderId}/mock-pay`)
      setNotice(`订单 #${orderId} 已支付成功,积分已入账。`)
      await load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const columns: TableColumnsType<OrderItem> = [
    { title: '套餐', dataIndex: 'package_name', key: 'package_name' },
    { title: '积分', dataIndex: 'credits', key: 'credits' },
    {
      title: '金额',
      dataIndex: 'price_cents',
      key: 'price_cents',
      render: (value: number) => yuan(value),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (value: string) => (
        <Tag color={STATUS_COLOR[value] ?? 'default'}>{STATUS_TEXT[value] ?? value}</Tag>
      ),
    },
    {
      title: '渠道',
      dataIndex: 'channel',
      key: 'channel',
      render: (value: string) => (value === 'manual' ? '人工确认' : '模拟支付'),
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (value?: string) => (value ? value.replace('T', ' ').slice(0, 16) : '-'),
    },
    {
      title: '操作',
      key: 'action',
      render: (_, order) =>
        status?.dev_mode && order.status === 'pending' ? (
          <Button size="small" loading={loading} onClick={() => void mockPay(order.id)}>
            模拟支付
          </Button>
        ) : null,
    },
  ]

  return (
    <div className="page-stack">
      <div className="package-grid">
        <Card>
          <Statistic title="可用积分" value={balance?.available ?? 0} suffix="积分" />
          <Typography.Text type="secondary">
            冻结中 {balance?.held ?? 0} · 累计 {balance?.balance ?? 0}
          </Typography.Text>
        </Card>
        <Card>
          <Typography.Title level={5} style={{ marginTop: 0 }}>
            积分说明
          </Typography.Title>
          <Typography.Text type="secondary">
            对话按用量扣减积分。套餐的积分与售价之间没有换算关系,售价仅代表套餐价格。
          </Typography.Text>
        </Card>
      </div>

      {notice && <Alert type="success" showIcon message={notice} />}
      {error && <Alert type="error" showIcon message={error} />}

      <div>
        <Typography.Title level={5}>可选套餐</Typography.Title>
        <div className="package-grid">
          {packages.map((pkg) => (
            <Card key={pkg.id} title={pkg.name}>
              <Space direction="vertical" size="small" style={{ width: '100%' }}>
                <Typography.Text type="secondary">
                  {pkg.description ?? '套餐内含积分,用于对话与评估。'}
                </Typography.Text>
                <Space>
                  <Tag color="green">{pkg.credits} 积分</Tag>
                  <Tag color="gold">{yuan(pkg.price_cents)}</Tag>
                </Space>
                <Space wrap>
                  {status?.dev_mode && (
                    <Button type="primary" loading={loading} onClick={() => void buy(pkg, 'mock')}>
                      创建订单(模拟支付)
                    </Button>
                  )}
                  <Button loading={loading} onClick={() => void buy(pkg, 'manual')}>
                    创建订单(人工确认)
                  </Button>
                </Space>
              </Space>
            </Card>
          ))}
        </div>
        {packages.length === 0 && <Typography.Text type="secondary">暂无可用套餐。</Typography.Text>}
      </div>

      <Card title="订单记录">
        <Table<OrderItem>
          rowKey="id"
          columns={columns}
          dataSource={orders}
          pagination={false}
          locale={{ emptyText: '暂无订单' }}
        />
      </Card>
    </div>
  )
}
