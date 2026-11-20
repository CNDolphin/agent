import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { renderApp } from '../test/renderApp'
import { saveSession } from '../api/session'

describe('用户查询页', () => {
  beforeEach(() => {
    saveSession({ token: 'token-super', role: 'super', username: 'admin' })
  })

  it('只展示脱敏手机号与余额信息', async () => {
    renderApp('/users')

    fireEvent.change(screen.getByPlaceholderText('输入完整手机号查询'), {
      target: { value: '13812345678' },
    })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))

    expect(await screen.findByText('138****1234')).toBeInTheDocument()
    expect(screen.queryByText('13812345678')).not.toBeInTheDocument()
    expect(screen.getByText('余额')).toBeInTheDocument()
  })

  it('可查看用户的积分流水分页列表', async () => {
    renderApp('/users')

    fireEvent.change(screen.getByPlaceholderText('输入完整手机号查询'), {
      target: { value: '13812345678' },
    })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    await screen.findByText('138****1234')

    fireEvent.click(screen.getByRole('button', { name: '查看流水' }))

    expect(await screen.findByText('注册赠送')).toBeInTheDocument()
    expect(screen.getByText('消费')).toBeInTheDocument()
  })
})
