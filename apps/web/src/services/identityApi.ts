import { identityRequest } from './api'
import type { User, AuthTokens, LoginRequest, RegisterRequest } from '@trading/types'

interface AuthResponse {
  user: User
  tokens: AuthTokens
}

export async function login(req: LoginRequest): Promise<AuthResponse> {
  return identityRequest<AuthResponse>('/auth/login', {
    method: 'POST',
    body: req,
    authenticated: false,
  })
}

export async function register(req: RegisterRequest): Promise<AuthResponse> {
  return identityRequest<AuthResponse>('/auth/register', {
    method: 'POST',
    body: req,
    authenticated: false,
  })
}

export async function refreshToken(refreshToken: string): Promise<AuthTokens> {
  return identityRequest<AuthTokens>('/auth/refresh', {
    method: 'POST',
    body: { refreshToken },
    authenticated: false,
  })
}

export async function getMe(): Promise<User> {
  return identityRequest<User>('/users/me')
}

export async function updateProfile(data: { username?: string }): Promise<User> {
  return identityRequest<User>('/users/me', { method: 'PATCH', body: data })
}

export async function enableTotp(): Promise<{ qrCode: string; secret: string }> {
  return identityRequest('/auth/totp/enable', { method: 'POST' })
}

export async function verifyTotp(code: string): Promise<void> {
  return identityRequest('/auth/totp/verify', { method: 'POST', body: { code } })
}

export async function logout(): Promise<void> {
  return identityRequest('/auth/logout', { method: 'POST' })
}
