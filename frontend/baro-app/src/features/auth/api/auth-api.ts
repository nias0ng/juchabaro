import { getJson, postJson } from '@/services/http-client';

import type { LoginRequest, LoginResult, UserProfile } from './types';

// 로그인 API 호출
export function login(request: LoginRequest): Promise<LoginResult> {
  return postJson<LoginResult>('/api/auth/login', request); // 로그인 API 호출
}

// 로그인 상태를 복원할 때 사용
export function getMyProfile(accessToken: string): Promise<UserProfile> {
  return getJson<UserProfile>('/api/users/me', accessToken);
}
