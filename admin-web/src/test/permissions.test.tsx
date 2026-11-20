import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, within } from '@testing-library/react'
import { renderApp } from '../test/renderApp'
import { saveSession } from '../api/session'

describe('ops 角色权限', () => {
  beforeEach(() => {
    saveSession({ token: 'token-ops', role: 'ops', username: 'ops' })
  })

  it('隐藏仅 super 可用的积分发放入口', async () => {
    renderApp('/prices')
    await screen.findByText('deepseek-flash')

    expect(screen.queryByText('积分发放')).not.toBeInTheDocument()
    expect(screen.queryByText('检测报告')).not.toBeInTheDocument()
    expect(screen.getByText('订单管理')).toBeInTheDocument()
  })

  it('ops 直接访问检测报告页时展示无权访问', async () => {
    renderApp('/reports')

    expect(await screen.findByText('无权访问')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '上传报告' })).not.toBeInTheDocument()
  })

  it('直接访问积分发放页时展示无权访问', async () => {
    renderApp('/credits/grant')

    expect(await screen.findByText('无权访问')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '提交发放' })).not.toBeInTheDocument()
  })

  it('订单页不展示确认收款与取消操作', async () => {
    renderApp('/orders')
    const cell = await screen.findByText('138****1234')
    const row = cell.closest('tr') as HTMLElement

    expect(within(row).queryByRole('button', { name: '确认收款' })).toBeNull()
    expect(within(row).queryByRole('button', { name: '取消' })).toBeNull()
  })

  it('ops 仍可访问只读的用量与通知页面', async () => {
    renderApp('/usage')

    expect(await screen.findByText('deepseek-flash')).toBeInTheDocument()
    fireEvent.click(screen.getByText('通知记录'))

    expect(await screen.findByText('crisis_contact_v1')).toBeInTheDocument()
  })
})
