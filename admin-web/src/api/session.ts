import { useSyncExternalStore } from 'react'

const TOKEN_KEY = 'admin_token'
const ROLE_KEY = 'admin_role'
const NAME_KEY = 'admin_username'

export type AdminRole = 'super' | 'ops'

const listeners = new Set<() => void>()

function notify(): void {
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function getRole(): AdminRole | null {
  const role = sessionStorage.getItem(ROLE_KEY)
  return role === 'super' || role === 'ops' ? role : null
}

export function getUsername(): string | null {
  return sessionStorage.getItem(NAME_KEY)
}

export interface AdminSession {
  token: string
  role: AdminRole
  username: string
}

export function saveSession(session: AdminSession): void {
  sessionStorage.setItem(TOKEN_KEY, session.token)
  sessionStorage.setItem(ROLE_KEY, session.role)
  sessionStorage.setItem(NAME_KEY, session.username)
  notify()
}

export function clearSession(): void {
  sessionStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(ROLE_KEY)
  sessionStorage.removeItem(NAME_KEY)
  notify()
}

export function useSessionToken(): string | null {
  return useSyncExternalStore(subscribe, getToken)
}

export function useSessionRole(): AdminRole | null {
  return useSyncExternalStore(subscribe, getRole)
}
