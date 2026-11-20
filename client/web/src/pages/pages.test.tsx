import { expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { MAIN_PROFILE, makeProfile, setMockState } from '../test/handlers'
import type { MockReport } from '../test/handlers'
import { renderApp } from '../test/renderApp'

const NOW = '2026-11-09T06:00:00+00:00'

function makeReport(partial: Partial<MockReport>): MockReport {
  return {
    report_id: 1,
    version: 1,
    title: 'PHQ-9 检测报告',
    filename: 'phq9.pdf',
    path: 'documents/phq9.pdf',
    abs_path: '/Users/me/.mhagent-data/documents/phq9.pdf',
    size_bytes: 2048,
    content_type: 'application/pdf',
    created_at: NOW,
    downloaded_at: NOW,
    read_at: null,
    ...partial,
  }
}

function readyState() {
  setMockState({
    logged_in: true,
    consent_version: 'v1',
    profiles: [{ ...MAIN_PROFILE }],
    active_profile_id: 'main',
  })
}

it('主账号用手机号 + 密码登录后进入同意书', async () => {
  const user = userEvent.setup()
  renderApp('/login')

  expect(await screen.findByRole('heading', { name: '登录本地助手' })).toBeInTheDocument()
  await user.type(screen.getByLabelText('手机号'), '13800138000')
  await user.type(screen.getByLabelText('密码'), 'password123')
  await user.click(screen.getByRole('button', { name: /登\s*录/ }))

  expect(await screen.findByRole('heading', { name: '使用说明与知情同意' })).toBeInTheDocument()
})

it('首次注册用验证码设置密码后自动登录', async () => {
  const user = userEvent.setup()
  renderApp('/login')

  await user.click(await screen.findByRole('tab', { name: '首次注册' }))
  await user.type(screen.getByLabelText('注册手机号'), '13800138000')
  await user.click(screen.getByRole('button', { name: '获取开发验证码' }))
  await waitFor(() => expect(screen.getByLabelText('注册验证码')).toHaveValue('123456'))
  await user.type(screen.getByLabelText('设置密码'), 'password123')
  await user.click(screen.getByRole('button', { name: '注册并登录' }))

  expect(await screen.findByRole('heading', { name: '使用说明与知情同意' })).toBeInTheDocument()
})

it('旧版口令数据可在界面完成一次性升级', async () => {
  const user = userEvent.setup()
  setMockState({ legacy_required: true, logged_in: false })
  renderApp('/migrate')

  expect(await screen.findByRole('heading', { name: '升级旧版本地数据' })).toBeInTheDocument()
  await user.type(screen.getByLabelText('旧口令'), 'old-pass')
  await user.click(screen.getByRole('button', { name: '升级并继续' }))

  expect(await screen.findByRole('heading', { name: '登录本地助手' })).toBeInTheDocument()
})

it('用户管理可新建子账号并切换到该档案', async () => {
  const user = userEvent.setup()
  readyState()
  renderApp('/profiles')

  expect(await screen.findByRole('heading', { name: '用户管理' })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '新建子账号' }))
  await user.type(screen.getByLabelText('昵称'), '小明')
  await user.type(screen.getByLabelText('登录账号'), 'xiaoming')
  await user.type(screen.getByLabelText('登录密码'), 'password-1')
  await user.click(screen.getByRole('button', { name: /创\s*建/ }))

  expect(await screen.findByText('小明')).toBeInTheDocument()
  const row = screen.getByRole('row', { name: /小明/ })
  await user.click(within(row).getByRole('button', { name: /切\s*换/ }))

  expect(await screen.findByRole('heading', { name: '对话支持' })).toBeInTheDocument()
})

it('唯一会话可直接重命名', async () => {
  const user = userEvent.setup()
  readyState()
  setMockState({
    sessions: [
      {
        session_id: 's_1',
        title: '我的会话',
        created_at: NOW,
        updated_at: NOW,
        messages: [],
      },
    ],
  })
  renderApp('/')

  expect(await screen.findByText('我的会话')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '新建会话' })).not.toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: '重命名' }))
  const input = await screen.findByLabelText('会话标题')
  await user.clear(input)
  await user.type(input, '睡前情绪')
  await user.click(screen.getByRole('button', { name: /保\s*存/ }))

  expect(await screen.findByText('睡前情绪')).toBeInTheDocument()
})

it('未完成测评时自动进入入学测评', async () => {
  readyState()
  setMockState({ onboarding_status: 'draft' })
  renderApp('/')

  expect(await screen.findByRole('heading', { name: '入学测评' })).toBeInTheDocument()
  expect(await screen.findByText('语言智能')).toBeInTheDocument()
  expect(screen.getByLabelText('题目 1')).toBeInTheDocument()
  expect(screen.queryByLabelText('题目 2')).not.toBeInTheDocument()
})

it('答完正向题后进入同一指标的配对题并可回退', async () => {
  const user = userEvent.setup()
  readyState()
  setMockState({ onboarding_status: 'draft' })
  renderApp('/onboarding')

  const first = await screen.findByLabelText('题目 1')
  expect(screen.queryByLabelText('题目 2')).not.toBeInTheDocument()

  await user.click(within(first).getByRole('radio', { name: '完全符合' }))

  const paired = await screen.findByLabelText('题目 2')
  expect(
    screen.getByText('本题与该指标的正向题配对，测的是同一个方面，请按真实情况独立作答。'),
  ).toBeInTheDocument()
  expect(within(paired).getByRole('radio', { name: '完全符合' })).toBeInTheDocument()
  expect(screen.queryByLabelText('题目 1')).not.toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: '上一题' }))
  expect(await screen.findByLabelText('题目 1')).toBeInTheDocument()
})

it('答满十项后可排序并完成测评', async () => {
  const user = userEvent.setup()
  readyState()
  setMockState({ onboarding_status: 'draft' })
  renderApp('/onboarding')

  expect(await screen.findByRole('heading', { name: '入学测评' })).toBeInTheDocument()
  for (let id = 1; id <= 20; id += 1) {
    const group = await screen.findByLabelText(`题目 ${id}`)
    await user.click(within(group).getByRole('radio', { name: '完全符合' }))
  }

  await user.click(await screen.findByRole('button', { name: '进入排序' }))
  expect(await screen.findByText('八大智能排序（从最强到最弱）')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '下一步：基因报告' }))
  expect(await screen.findByText('上传基因检测报告（可选）')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /完成测评/ }))

  expect(await screen.findByText('你的基础测评结果')).toBeInTheDocument()
  expect(await screen.findByRole('button', { name: '进入对话' })).toBeInTheDocument()
})

it('已完成测评可直接查看结果摘要', async () => {
  readyState()
  setMockState({ onboarding_status: 'completed' })
  renderApp('/onboarding')

  expect(await screen.findByText('你的基础测评结果')).toBeInTheDocument()
  expect(await screen.findByRole('button', { name: '进入对话' })).toBeInTheDocument()
})

it('高风险对话置顶展示危机卡片', async () => {
  const user = userEvent.setup()
  readyState()
  renderApp('/')

  expect(await screen.findByLabelText('消息输入')).toBeInTheDocument()
  await user.type(screen.getByLabelText('消息输入'), '我想自杀')
  await user.click(screen.getByRole('button', { name: /发\s*送/ }))

  expect(await screen.findByText('此刻的安全支持')).toBeInTheDocument()
  expect((await screen.findAllByText(/12356/)).length).toBeGreaterThan(0)
})

it('PHQ-9 第 9 题阳性时展示高危结果与求助热线', async () => {
  const user = userEvent.setup()
  readyState()
  renderApp('/assessment')

  expect(await screen.findByRole('heading', { name: '量表评估' })).toBeInTheDocument()
  await screen.findAllByRole('button', { name: '开始评估' })
  expect(screen.getByRole('button', { name: '暂不可用' })).toBeDisabled()

  await user.click(screen.getAllByRole('button', { name: '开始评估' })[0])

  for (let index = 0; index < 8; index += 1) {
    await user.click(await screen.findByRole('radio', { name: '完全不会' }))
    await waitFor(() => {
      expect(screen.getByText(`第 ${index + 2}/9 题`)).toBeInTheDocument()
    })
  }
  await user.click(screen.getByRole('radio', { name: '几乎每天' }))

  expect(await screen.findByText('评估结果')).toBeInTheDocument()
  expect(await screen.findByText(/重度/)).toBeInTheDocument()
  expect((await screen.findAllByText(/12356/)).length).toBeGreaterThan(0)
})

it('创建订单后可用模拟支付入账', async () => {
  const user = userEvent.setup()
  readyState()
  renderApp('/credits')

  expect(await screen.findByText('体验包')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '创建订单(模拟支付)' }))

  expect(await screen.findByText('待支付')).toBeInTheDocument()
  await user.click(await screen.findByRole('button', { name: '模拟支付' }))

  expect(await screen.findByText(/已支付成功/)).toBeInTheDocument()
  expect(await screen.findByText('已支付')).toBeInTheDocument()
})

it('设置页退出登录后回到登录页', async () => {
  const user = userEvent.setup()
  readyState()
  renderApp('/settings')

  await user.click(await screen.findByRole('button', { name: '退出登录' }))

  expect(await screen.findByRole('heading', { name: '登录本地助手' })).toBeInTheDocument()
})

it('局域网模式用子账号用户名 + 密码登录且不显示管理入口', async () => {
  const user = userEvent.setup()
  setMockState({
    device_mode: 'lan',
    logged_in: false,
    consent_version: 'v1',
    profiles: [
      { ...MAIN_PROFILE },
      makeProfile({
        id: 'p_1',
        role: 'sub',
        nickname: '小明',
        username: 'xiaoming',
        phone_mask: '',
      }),
    ],
    active_profile_id: 'main',
  })
  renderApp('/login')

  expect(await screen.findByRole('heading', { name: '子账号登录' })).toBeInTheDocument()
  await user.type(screen.getByLabelText('登录账号'), 'xiaoming')
  await user.type(screen.getByLabelText('登录密码'), 'password-1')
  await user.click(screen.getByRole('button', { name: /登\s*录/ }))

  expect(await screen.findByRole('heading', { name: '对话支持' })).toBeInTheDocument()
  expect(screen.queryByText('用户管理')).not.toBeInTheDocument()
  expect(screen.queryByText('积分与套餐')).not.toBeInTheDocument()
})

it('我的报告展示已下载的报告与未读状态', async () => {
  readyState()
  setMockState({
    reports: [
      makeReport({ report_id: 2, title: 'PHQ-9 检测报告', filename: 'phq9-2026-11.pdf' }),
      makeReport({
        report_id: 1,
        title: 'GAD-7 检测报告',
        filename: 'gad7-2026-10.pdf',
        read_at: NOW,
      }),
    ],
  })
  renderApp('/reports')

  expect(await screen.findByRole('heading', { name: '我的报告' })).toBeInTheDocument()
  expect(await screen.findByText('PHQ-9 检测报告')).toBeInTheDocument()
  expect(screen.getAllByText('文件路径').length).toBeGreaterThan(0)
  expect(
    screen.getAllByText('/Users/me/.mhagent-data/documents/phq9.pdf').length,
  ).toBeGreaterThan(0)
  expect(screen.getByText('GAD-7 检测报告')).toBeInTheDocument()
  expect(screen.getByText('未读')).toBeInTheDocument()
  expect(screen.getByText('已读')).toBeInTheDocument()
})

it('检查新报告会拉取并展示新下载的报告', async () => {
  const user = userEvent.setup()
  readyState()
  setMockState({
    pending_reports: [
      makeReport({ report_id: 9, title: 'SDS 检测报告', filename: 'sds-2026-11.pdf' }),
    ],
  })
  renderApp('/reports')

  expect(await screen.findByText('暂无检测报告')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '检查新报告' }))

  expect(await screen.findByText('SDS 检测报告')).toBeInTheDocument()
  expect(await screen.findByText(/已下载 1 份新报告/)).toBeInTheDocument()
})

it('打开报告文件后自动标记为已读', async () => {
  const user = userEvent.setup()
  readyState()
  setMockState({
    reports: [makeReport({ report_id: 3, filename: 'phq9-2026-11.pdf' })],
  })
  renderApp('/reports')

  await user.click(await screen.findByRole('button', { name: '打开文件' }))

  expect(await screen.findByText(/已保存到本机下载目录/)).toBeInTheDocument()
  await waitFor(() => expect(screen.queryByText('未读')).not.toBeInTheDocument())
  expect(screen.getByText('已读')).toBeInTheDocument()
})

it('局域网设备不展示我的报告入口', async () => {
  setMockState({
    device_mode: 'lan',
    logged_in: true,
    consent_version: 'v1',
    phone_mask: '138****8000',
    profiles: [{ ...MAIN_PROFILE }],
    active_profile_id: 'main',
    reports: [makeReport({})],
  })
  renderApp('/reports')

  expect(await screen.findByRole('heading', { name: '对话支持' })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: '我的报告' })).not.toBeInTheDocument()
})
