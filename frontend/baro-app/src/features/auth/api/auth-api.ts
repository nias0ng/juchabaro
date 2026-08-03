import { getJson, postJson } from '@/services/http-client';

import type { LoginRequest, LoginResult, SignupRequest, SignupResult, UserProfile } from './types';

// 로그인 API 호출
export function login(request: LoginRequest): Promise<LoginResult> {
  return postJson<LoginResult>('/api/auth/login', request); // 로그인 API 호출
}

// 로그인 상태를 복원할 때 사용
export function getMyProfile(accessToken: string): Promise<UserProfile> {
  return getJson<UserProfile>('/api/users/me', accessToken);
}

// 회원가입 API 호출. 성공해도 토큰은 내려오지 않아 자동 로그인은 하지 않는다.
export function signup(request: SignupRequest): Promise<SignupResult> {
  return postJson<SignupResult>('/api/auth/signup', request);
}
