import { render } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { MemoryRouter } from 'react-router-dom'

import App from '../App'
import { StatusProvider } from '../status'

export function renderApp(path = '/') {
  return render(
    <ConfigProvider locale={zhCN}>
      <MemoryRouter initialEntries={[path]}>
        <StatusProvider>
          <App />
        </StatusProvider>
      </MemoryRouter>
    </ConfigProvider>,
  )
}
