import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { renderApp } from '../test/renderApp'
import { saveSession } from '../api/session'
import { mockData } from '../test/handlers'

describe('检测报告页', () => {
  beforeEach(() => {
    saveSession({ token: 'token-super', role: 'super', username: 'admin' })
  })

  it('展示报告列表与投递状态', async () => {
    renderApp('/reports')

    expect(await screen.findByText('心理测评报告')).toBeInTheDocument()
    expect(screen.getByText('焦虑自评量表')).toBeInTheDocument()
    expect(screen.getByText('已读')).toBeInTheDocument()
    expect(screen.getByText('未通知')).toBeInTheDocument()
    expect(screen.getByText('138****1234')).toBeInTheDocument()
  })

  it('按关键词筛选报告', async () => {
    renderApp('/reports')
    await screen.findByText('心理测评报告')

    fireEvent.change(screen.getByPlaceholderText('标题或文件名关键词'), {
      target: { value: '焦虑' },
    })
    fireEvent.click(screen.getByRole('button', { name: '查询' }))

    await waitFor(() => {
      expect(screen.queryByText('心理测评报告')).not.toBeInTheDocument()
    })
    expect(screen.getByText('焦虑自评量表')).toBeInTheDocument()
  })

  it('上传报告时绑定用户并提交文件', async () => {
    renderApp('/reports')
    await screen.findByText('心理测评报告')

    fireEvent.click(screen.getByRole('button', { name: '上传报告' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByPlaceholderText('输入完整手机号'), {
      target: { value: '13812345678' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: '查询' }))
    await waitFor(() => {
      expect(within(dialog).getByText(/138\*\*\*\*1234/)).toBeInTheDocument()
    })

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(fileInput, {
      target: { files: [new File(['%PDF-1.4'], 'new-report.pdf', { type: 'application/pdf' })] },
    })
    await waitFor(() => {
      expect(within(dialog).getByText('new-report.pdf')).toBeInTheDocument()
    })
    fireEvent.click(within(dialog).getByRole('button', { name: '上传并通知' }))

    await waitFor(() => {
      const upload = mockData.requests.find(
        (item) => item.method === 'POST' && item.path === '/admin/reports',
      )
      expect(upload).toBeTruthy()
      expect(upload?.body).toMatchObject({ userId: '1001' })
    })
  })

  it('详情抽屉展示版本与投递时间线', async () => {
    renderApp('/reports')
    await screen.findByText('心理测评报告')

    fireEvent.click(screen.getAllByRole('button', { name: '详情' })[0])

    expect(await screen.findByText(/报告 #1/)).toBeInTheDocument()
    expect(screen.getByText(/上传：/)).toBeInTheDocument()
    expect(screen.getByText(/用户已读：/)).toBeInTheDocument()
    expect(screen.getAllByText('v2').length).toBeGreaterThan(0)
  })

  it('可删除报告并从列表移除', async () => {
    renderApp('/reports')
    await screen.findByText('焦虑自评量表')

    const row = screen.getByText('焦虑自评量表').closest('tr') as HTMLElement
    fireEvent.click(within(row).getByRole('button', { name: '删除' }))
    await waitFor(() => {
      expect(document.querySelector('.ant-popconfirm')).toBeTruthy()
    })
    const confirm = document.querySelector('.ant-popconfirm .ant-btn-primary') as HTMLElement
    fireEvent.click(confirm)

    await waitFor(() => {
      expect(screen.queryByText('焦虑自评量表')).not.toBeInTheDocument()
    })
  })
})
