import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { renderApp } from '../test/renderApp'
import { mockData } from '../test/handlers'
import { saveSession } from '../api/session'

describe('订单管理页', () => {
  beforeEach(() => {
    saveSession({ token: 'token-super', role: 'super', username: 'admin' })
  })

  it('manual 渠道待支付订单需二次确认后才能确认收款', async () => {
    renderApp('/orders')

    const cell = await screen.findByText('138****1234')
    const row = cell.closest('tr') as HTMLElement
    fireEvent.click(within(row).getByRole('button', { name: '确认收款' }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/确认已收到订单 #1/)).toBeInTheDocument()
    expect(within(dialog).getByText(/入账 100 积分/)).toBeInTheDocument()

    fireEvent.click(within(dialog).getByRole('button', { name: '确认收款' }))

    await waitFor(() => {
      const request = mockData.requests.find(
        (item) => item.method === 'POST' && item.path === '/admin/orders/1/confirm',
      )
      expect(request).toBeTruthy()
    })
  })

  it('已入账订单不展示任何操作按钮', async () => {
    renderApp('/orders')

    const cell = await screen.findByText('139****5678')
    const row = cell.closest('tr') as HTMLElement
    expect(within(row).getByText('已入账')).toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: '确认收款' })).toBeNull()
    expect(within(row).queryByRole('button', { name: '取消' })).toBeNull()
  })
})
