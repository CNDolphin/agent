import { useEffect, useMemo, useState } from 'react'
import type { TableProps } from 'antd'
import {
  Alert,
  App as AntApp,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Space,
  Switch,
  Table,
  Tag,
} from 'antd'
import { createPackage, listPackages, updatePackage } from '../api/admin'
import { ApiError } from '../api/client'
import type { PackageItem } from '../api/types'
import { PageError } from '../components/PageError'
import { PageHeader } from '../components/PageHeader'
import { formatMoney } from '../utils/format'

interface PackageFormValues {
  name: string
  description?: string
  price_yuan: number
  credits: number
  sort_order: number
}

function toPayload(values: PackageFormValues) {
  return {
    name: values.name.trim(),
    description: values.description?.trim() ?? '',
    price_cents: Math.round((values.price_yuan ?? 0) * 100),
    credits: values.credits,
    sort_order: values.sort_order ?? 0,
  }
}

export function PackagesPage() {
  const { message } = AntApp.useApp()
  const [form] = Form.useForm<PackageFormValues>()
  const [rows, setRows] = useState<PackageItem[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<PackageItem | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const load = useMemo(
    () => async () => {
      setLoading(true)
      setLoadError(null)
      try {
        const data = await listPackages()
        setRows(data.items ?? [])
      } catch (err) {
        setLoadError(err instanceof ApiError ? err.message : '加载套餐失败')
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    void load()
  }, [load])

  const openCreate = () => {
    setEditing(null)
    setActionError(null)
    form.resetFields()
    form.setFieldsValue({ price_yuan: 0, credits: 1, sort_order: 0, description: '' })
    setModalOpen(true)
  }

  const openEdit = (record: PackageItem) => {
    setEditing(record)
    setActionError(null)
    form.resetFields()
    form.setFieldsValue({
      name: record.name,
      description: record.description,
      price_yuan: record.price_cents / 100,
      credits: record.credits,
      sort_order: record.sort_order,
    })
    setModalOpen(true)
  }

  const handleSubmit = async (values: PackageFormValues) => {
    setSubmitting(true)
    setActionError(null)
    try {
      const payload = toPayload(values)
      if (editing) {
        await updatePackage(editing.id, payload)
        message.success('套餐已更新')
      } else {
        await createPackage(payload)
        message.success('套餐已创建（默认下架，请手动上架）')
      }
      setModalOpen(false)
      await load()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '保存失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  const handleToggle = async (record: PackageItem, enabled: boolean) => {
    setActionError(null)
    try {
      await updatePackage(record.id, {
        name: record.name,
        description: record.description,
        price_cents: record.price_cents,
        credits: record.credits,
        sort_order: record.sort_order,
        enabled,
      })
      setRows((previous) =>
        previous.map((row) => (row.id === record.id ? { ...row, enabled } : row)),
      )
      message.success(enabled ? '套餐已上架' : '套餐已下架')
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '更新上下架状态失败')
    }
  }

  const columns: TableProps<PackageItem>['columns'] = [
    { title: '名称', dataIndex: 'name', width: 180 },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    {
      title: '售价（元，仅展示）',
      dataIndex: 'price_cents',
      width: 160,
      render: (value: number) => formatMoney(value),
    },
    { title: '赠送积分', dataIndex: 'credits', width: 110 },
    { title: '排序', dataIndex: 'sort_order', width: 80 },
    {
      title: '状态',
      dataIndex: 'enabled',
      width: 130,
      render: (value: boolean, record) => (
        <Space size={8}>
          <Switch checked={value} onChange={(checked) => void handleToggle(record, checked)} />
          <Tag color={value ? 'green' : 'default'}>{value ? '已上架' : '已下架'}</Tag>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 90,
      render: (_: unknown, record) => (
        <Button type="link" onClick={() => openEdit(record)}>
          编辑
        </Button>
      ),
    },
  ]

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <PageHeader
        code="M-02"
        title="套餐管理"
        description="售价只用于展示与记录；赠送积分是独立配置的数量，系统内不存在「元 → 积分」的换算。上架前请自行核算赠送积分与上游成本。"
        actions={
          <Button type="primary" onClick={openCreate}>
            新建套餐
          </Button>
        }
      />

      <Alert
        type="info"
        showIcon
        title="积分与售价无换算关系"
        description="售价（元）只用于展示与记录；赠送积分是独立配置的数量，系统内不存在「元 → 积分」的换算。上架前请自行核算赠送积分与上游成本。"
      />

      {loadError ? <PageError message={loadError} onRetry={() => void load()} /> : null}
      {actionError ? <Alert type="error" showIcon title={actionError} /> : null}

      <Table<PackageItem>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: '暂无套餐，请先新建' }}
      />

      <Modal
        title={editing ? `编辑套餐 · ${editing.name}` : '新建套餐'}
        open={modalOpen}
        okText="保存"
        cancelText="取消"
        confirmLoading={submitting}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
      >
        <Form<PackageFormValues> form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            label="套餐名称"
            name="name"
            rules={[{ required: true, message: '请输入套餐名称' }]}
          >
            <Input placeholder="例如：基础包" maxLength={60} />
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input.TextArea rows={2} placeholder="展示给用户的说明（可选）" maxLength={200} />
          </Form.Item>
          <Form.Item
            label="售价（元，仅展示与记录）"
            name="price_yuan"
            rules={[
              { required: true, message: '请输入售价' },
              { type: 'number', min: 0, message: '售价不能为负数' },
            ]}
          >
            <InputNumber precision={2} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            label="赠送积分"
            name="credits"
            rules={[
              { required: true, message: '请输入赠送积分' },
              { type: 'number', min: 1, message: '赠送积分必须大于 0，且为整数' },
            ]}
          >
            <InputNumber precision={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="排序（越小越靠前）" name="sort_order">
            <InputNumber precision={0} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
