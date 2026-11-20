import { useCallback, useEffect, useMemo, useState } from 'react'
import type { TableProps } from 'antd'
import { Card, Col, DatePicker, Row, Space, Statistic, Table, Typography, Alert } from 'antd'
import dayjs from 'dayjs'
import type { Dayjs } from 'dayjs'
import { usageSummary } from '../api/admin'
import { ApiError } from '../api/client'
import type { UsageSummaryItem } from '../api/types'
import { PageError } from '../components/PageError'
import { PageHeader } from '../components/PageHeader'

const { RangePicker } = DatePicker

const COLUMNS: TableProps<UsageSummaryItem>['columns'] = [
  { title: '模型', dataIndex: 'model', width: 200 },
  { title: '请求数', dataIndex: 'requests', width: 110 },
  { title: '命中输入 token', dataIndex: 'in_hit', width: 150 },
  { title: '未命中输入 token', dataIndex: 'in_miss', width: 170 },
  { title: '输出 token', dataIndex: 'out', width: 130 },
  { title: '消耗积分', dataIndex: 'cost', width: 110 },
]

export function UsagePage() {
  const initialRange = useMemo<[Dayjs, Dayjs]>(() => [dayjs().subtract(6, 'day'), dayjs()], [])
  const [range, setRange] = useState<[Dayjs, Dayjs]>(initialRange)
  const [rows, setRows] = useState<UsageSummaryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const load = useCallback(async (from: Dayjs, to: Dayjs) => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await usageSummary({
        from: from.startOf('day').toISOString(),
        to: to.endOf('day').toISOString(),
      })
      setRows(data.items ?? [])
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : '加载用量汇总失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(initialRange[0], initialRange[1])
  }, [initialRange, load])

  const totals = rows.reduce(
    (accumulator, item) => ({
      requests: accumulator.requests + item.requests,
      cost: accumulator.cost + item.cost,
      tokens: accumulator.tokens + item.in_hit + item.in_miss + item.out,
    }),
    { requests: 0, cost: 0, tokens: 0 },
  )

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader
        code="M-05"
        title="用量汇总"
        description="按模型与日期核对请求量、token 与积分消耗，用于成本复核。"
      />

      <Alert
        type="info"
        showIcon
        title="只统计 token 数量与积分消耗，不包含任何对话内容。"
      />

      <Space wrap>
        <RangePicker
          value={range}
          allowClear={false}
          onChange={(dates) => {
            if (dates && dates[0] && dates[1]) {
              const next: [Dayjs, Dayjs] = [dates[0], dates[1]]
              setRange(next)
              void load(next[0], next[1])
            }
          }}
        />
        <Typography.Text type="secondary">
          统计区间：{range[0].format('YYYY-MM-DD')} 至 {range[1].format('YYYY-MM-DD')}
        </Typography.Text>
      </Space>

      {loadError ? (
        <PageError message={loadError} onRetry={() => void load(range[0], range[1])} />
      ) : null}

      <Row gutter={16}>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic title="总请求数" value={totals.requests} />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic title="总 token 数" value={totals.tokens} />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic title="总消耗积分" value={totals.cost} />
          </Card>
        </Col>
      </Row>

      <Table<UsageSummaryItem>
        rowKey="model"
        loading={loading}
        columns={COLUMNS}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: '该时间段内暂无用量记录' }}
      />
    </Space>
  )
}
