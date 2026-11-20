import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { renderApp } from '../test/renderApp'
import { mockData } from '../test/handlers'
import { saveSession } from '../api/session'

describe('套餐管理页', () => {
  beforeEach(() => {
    saveSession({ token: 'token-super', role: 'super', username: 'admin' })
  })

  it('明确提示积分与售价无换算关系，且售价只读展示', async () => {
    renderApp('/packages')

    expect(await screen.findByText('体验包')).toBeInTheDocument()
    expect(screen.getByText('积分与售价无换算关系')).toBeInTheDocument()
    expect(screen.getByText('¥9.90')).toBeInTheDocument()
    expect(screen.getByText('¥29.90')).toBeInTheDocument()
  })

  it('赠送积分小于等于 0 时表单拒绝提交', async () => {
    renderApp('/packages')
    await screen.findByText('体验包')

    fireEvent.click(screen.getByRole('button', { name: '新建套餐' }))
    const dialog = await screen.findByRole('dialog')

    fireEvent.change(within(dialog).getByLabelText('套餐名称'), {
      target: { value: '测试套餐' },
    })
    fireEvent.change(within(dialog).getByLabelText('赠送积分'), { target: { value: '0' } })
    fireEvent.click(within(dialog).getByRole('button', { name: '保存' }))

    expect(await screen.findByText('赠送积分必须大于 0，且为整数')).toBeInTheDocument()
    expect(
      mockData.requests.filter(
        (item) => item.method === 'POST' && item.path === '/admin/packages',
      ),
    ).toHaveLength(0)
  })

  it('上下架开关会调用更新接口', async () => {
    renderApp('/packages')
    const cell = await screen.findByText('体验包')
    const row = cell.closest('tr') as HTMLElement

    fireEvent.click(within(row).getByRole('switch'))

    await waitFor(() => {
      const request = mockData.requests.find(
        (item) => item.method === 'PUT' && item.path === '/admin/packages/1',
      )
      expect(request).toBeTruthy()
      expect(request?.body).toMatchObject({ enabled: false })
    })
  })
})
