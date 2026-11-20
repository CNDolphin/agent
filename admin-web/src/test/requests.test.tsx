import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { renderApp } from '../test/renderApp'
import { server } from '../test/server'
import { saveSession } from '../api/session'

describe('请求层错误处理', () => {
  beforeEach(() => {
    saveSession({ token: 'token-super', role: 'super', username: 'admin' })
  })

  it('401 时清空令牌并跳转登录页', async () => {
    server.use(
      http.get('*/admin/prices', () =>
        HttpResponse.json({ code: 40101, message: '令牌已过期，请重新登录' }, { status: 401 }),
      ),
    )

    renderApp('/prices')

    await waitFor(() => {
      expect(sessionStorage.getItem('admin_token')).toBeNull()
    })
    expect(await screen.findByText('管理后台登录')).toBeInTheDocument()
  })

  it('网络错误时展示可重试提示，点击重试后恢复', async () => {
    server.use(http.get('*/admin/prices', () => HttpResponse.error(), { once: true }))

    renderApp('/prices')

    expect(
      await screen.findByText('网络连接失败，请检查网络后重试'),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '重试' }))

    expect(await screen.findByText('deepseek-flash')).toBeInTheDocument()
    expect(screen.queryByText('网络连接失败，请检查网络后重试')).not.toBeInTheDocument()
  })
})
