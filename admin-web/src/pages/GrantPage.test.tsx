import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { renderApp } from '../test/renderApp'
import { mockData } from '../test/handlers'
import { server } from '../test/server'
import { saveSession } from '../api/session'

describe('积分发放页', () => {
  beforeEach(() => {
    saveSession({ token: 'token-super', role: 'super', username: 'admin' })
  })

  it('原因必填，未填写时不会提交', async () => {
    renderApp('/credits/grant')
    await screen.findByRole('heading', { name: '手动发放积分', level: 1 })

    fireEvent.change(screen.getByLabelText('手机号'), { target: { value: '13812345678' } })
    fireEvent.click(screen.getByRole('button', { name: '提交发放' }))

    expect(await screen.findByText('请填写发放原因')).toBeInTheDocument()
    expect(
      mockData.requests.filter(
        (item) => item.method === 'POST' && item.path === '/admin/credits/grant',
      ),
    ).toHaveLength(0)
  })

  it('提交时自动生成 request_id 并携带发放原因', async () => {
    renderApp('/credits/grant')
    await screen.findByRole('heading', { name: '手动发放积分', level: 1 })

    const requestIdInput = screen.getByLabelText('request_id') as HTMLInputElement
    expect(requestIdInput.value).toMatch(/^admin-grant-/)
    const submittedRequestId = requestIdInput.value

    fireEvent.change(screen.getByLabelText('手机号'), { target: { value: '13812345678' } })
    fireEvent.change(screen.getByLabelText('发放原因'), {
      target: { value: '客服补偿，工单 #1234' },
    })
    fireEvent.click(screen.getByRole('button', { name: '提交发放' }))

    await waitFor(() => {
      const request = mockData.requests.find(
        (item) => item.method === 'POST' && item.path === '/admin/credits/grant',
      )
      expect(request?.body).toMatchObject({
        phone: '13812345678',
        amount: 100,
        reason: '客服补偿，工单 #1234',
        request_id: submittedRequestId,
      })
    })
  })

  it('超过单笔上限时展示后端返回的提示', async () => {
    server.use(
      http.post('*/admin/credits/grant', () =>
        HttpResponse.json(
          { code: 40001, message: '单笔发放不能超过 1000 积分' },
          { status: 400 },
        ),
      ),
    )

    renderApp('/credits/grant')
    await screen.findByRole('heading', { name: '手动发放积分', level: 1 })

    fireEvent.change(screen.getByLabelText('手机号'), { target: { value: '13812345678' } })
    fireEvent.change(screen.getByLabelText('发放原因'), {
      target: { value: '批量补偿' },
    })
    fireEvent.change(screen.getByLabelText('发放积分数量'), {
      target: { value: '5000' },
    })
    fireEvent.click(screen.getByRole('button', { name: '提交发放' }))

    expect(await screen.findByText('单笔发放不能超过 1000 积分')).toBeInTheDocument()
  })
})
