import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { renderApp } from '../test/renderApp'
import { mockData } from '../test/handlers'
import { saveSession } from '../api/session'

describe('模型定价页', () => {
  beforeEach(() => {
    saveSession({ token: 'token-super', role: 'super', username: 'admin' })
  })

  it('渲染模型价格列表', async () => {
    renderApp('/prices')

    expect(await screen.findByText('deepseek-flash')).toBeInTheDocument()
    expect(screen.getByText('deepseek-v4-pro')).toBeInTheDocument()
  })

  it('修改价格后保存会要求填写修改原因，原因为空时不能提交', async () => {
    renderApp('/prices')
    await screen.findByText('deepseek-flash')

    fireEvent.change(screen.getAllByRole('spinbutton')[0], { target: { value: '300' } })
    fireEvent.click(screen.getAllByRole('button', { name: '保存' })[0])

    expect(await screen.findByText('保存价格 · deepseek-flash')).toBeInTheDocument()
    const okButton = screen.getByRole('button', { name: '确认保存' })
    expect(okButton).toBeDisabled()

    fireEvent.change(screen.getByLabelText('修改原因'), {
      target: { value: '调整命中输入单价' },
    })
    expect(okButton).toBeEnabled()
    fireEvent.click(okButton)

    await waitFor(() => {
      const request = mockData.requests.find(
        (item) => item.method === 'PUT' && item.path === '/admin/prices/deepseek-flash',
      )
      expect(request).toBeTruthy()
      expect(request?.body).toMatchObject({
        in_hit_per_m: 300,
        reason: '调整命中输入单价',
      })
    })
  })

  it('负数价格被拒绝，且不会发起保存请求', async () => {
    renderApp('/prices')
    await screen.findByText('deepseek-flash')

    fireEvent.change(screen.getAllByRole('spinbutton')[0], { target: { value: '-5' } })
    fireEvent.click(screen.getAllByRole('button', { name: '保存' })[0])

    expect(await screen.findByText('命中输入单价不能为负数')).toBeInTheDocument()
    expect(mockData.requests.filter((item) => item.method === 'PUT')).toHaveLength(0)
    expect(screen.queryByText('确认保存')).not.toBeInTheDocument()
  })

  it('展开行可查看该模型的价格历史', async () => {
    renderApp('/prices')
    await screen.findByText('deepseek-flash')

    fireEvent.click(screen.getAllByRole('button', { name: '展开行' })[0])

    const historyRow = await screen.findByText('按上游成本初始化')
    expect(historyRow).toBeInTheDocument()
    const row = historyRow.closest('tr') as HTMLElement
    expect(within(row).getByText('3')).toBeInTheDocument()
  })
})
