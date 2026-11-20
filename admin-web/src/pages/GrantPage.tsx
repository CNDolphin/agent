import { useState } from 'react'
import {
  Alert,
  App as AntApp,
  Button,
  Form,
  Input,
  InputNumber,
  Radio,
  Space,
  Tag,
} from 'antd'
import { grantCredits } from '../api/admin'
import { ApiError } from '../api/client'
import { PageHeader } from '../components/PageHeader'
import { newRequestId } from '../utils/format'

interface GrantFormValues {
  mode: 'phone' | 'user_id'
  phone?: string
  user_id?: number
  amount: number
  reason: string
}

export function GrantPage() {
  const { message } = AntApp.useApp()
  const [form] = Form.useForm<GrantFormValues>()
  const [requestId, setRequestId] = useState(() => newRequestId())
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const mode = Form.useWatch('mode', form) ?? 'phone'

  const handleSubmit = async (values: GrantFormValues) => {
    setSubmitting(true)
    setError(null)
    setSuccess(null)
    try {
      const payload = {
        amount: values.amount,
        reason: values.reason.trim(),
        request_id: requestId,
        ...(values.mode === 'phone'
          ? { phone: (values.phone ?? '').trim() }
          : { user_id: Number(values.user_id) }),
      }
      await grantCredits(payload)
      message.success('积分发放成功')
      setSuccess(`已发放 ${values.amount} 积分，request_id：${requestId}`)
      setRequestId(newRequestId())
      form.setFieldsValue({ reason: '' })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '发放失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%', maxWidth: 720 }}>
      <PageHeader
        code="M-07"
        title="手动发放积分"
        tag={<Tag color="gold">超级管理员</Tag>}
        description="每次提交都必须填写原因，并携带自动生成的 request_id 以保证幂等；发放记录会写入审计日志。"
      />

      <Alert
        type="info"
        showIcon
        title="发放操作仅超级管理员可用"
        description="每次提交都必须填写原因，并携带自动生成的 request_id 以保证幂等；单笔上限由后端配置（Admin.MaxGrant）控制，超限会被拒绝。发放记录会写入审计日志。"
      />

      {error ? <Alert type="error" showIcon title={error} /> : null}
      {success ? <Alert type="success" showIcon title={success} /> : null}

      <Form<GrantFormValues>
        form={form}
        layout="vertical"
        initialValues={{ mode: 'phone', amount: 100, reason: '' }}
        onFinish={handleSubmit}
        disabled={submitting}
      >
        <Form.Item label="发放对象" name="mode">
          <Radio.Group
            options={[
              { value: 'phone', label: '按手机号' },
              { value: 'user_id', label: '按用户 ID' },
            ]}
          />
        </Form.Item>

        {mode === 'phone' ? (
          <Form.Item
            label="手机号"
            name="phone"
            rules={[{ required: true, message: '请输入手机号' }]}
          >
            <Input placeholder="中国大陆 11 位手机号" maxLength={11} />
          </Form.Item>
        ) : (
          <Form.Item
            label="用户 ID"
            name="user_id"
            rules={[{ required: true, message: '请输入用户 ID' }]}
          >
            <InputNumber min={1} precision={0} style={{ width: '100%' }} />
          </Form.Item>
        )}

        <Form.Item
          label="发放积分数量"
          name="amount"
          rules={[
            { required: true, message: '请输入发放数量' },
            { type: 'number', min: 1, message: '发放数量必须大于 0' },
          ]}
        >
          <InputNumber min={1} precision={0} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item
          label="发放原因"
          name="reason"
          rules={[{ required: true, whitespace: true, message: '请填写发放原因' }]}
        >
          <Input.TextArea rows={3} placeholder="例如：客服补偿，工单 #1234" maxLength={200} />
        </Form.Item>

        <Form.Item label="request_id（自动生成，用于幂等）">
          <Space.Compact style={{ width: '100%' }}>
            <Input value={requestId} readOnly aria-label="request_id" />
            <Button onClick={() => setRequestId(newRequestId())}>重新生成</Button>
          </Space.Compact>
        </Form.Item>

        <Button type="primary" htmlType="submit" loading={submitting}>
          提交发放
        </Button>
      </Form>
    </Space>
  )
}
