import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderApp } from '../test/renderApp'

describe('登录与鉴权', () => {
  it('登录成功后保存令牌并跳转到模型定价页', async () => {
    const user = userEvent.setup()
    renderApp('/login')

    await user.type(screen.getByLabelText('用户名'), 'admin')
    await user.type(screen.getByLabelText('密码'), 'admin123')
    await user.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(sessionStorage.getItem('admin_token')).toBe('token-super')
      expect(sessionStorage.getItem('admin_role')).toBe('super')
    })
    expect(
      await screen.findByRole('heading', { name: '模型定价', level: 1 }),
    ).toBeInTheDocument()
  })

  it('登录失败时展示后端错误信息', async () => {
    const user = userEvent.setup()
    renderApp('/login')

    await user.type(screen.getByLabelText('用户名'), 'admin')
    await user.type(screen.getByLabelText('密码'), 'wrong')
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByText('用户名或密码错误')).toBeInTheDocument()
    expect(sessionStorage.getItem('admin_token')).toBeNull()
  })

  it('未登录访问受保护路由时跳转到登录页', async () => {
    sessionStorage.clear()
    renderApp('/prices')

    expect(await screen.findByText('管理后台登录')).toBeInTheDocument()
    expect(screen.queryByText('模型定价')).not.toBeInTheDocument()
  })
})
