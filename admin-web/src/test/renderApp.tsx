import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AppProviders, AppRoutes } from '../App'

export function renderApp(initialPath = '/prices') {
  return render(
    <AppProviders>
      <MemoryRouter initialEntries={[initialPath]}>
        <AppRoutes />
      </MemoryRouter>
    </AppProviders>,
  )
}
