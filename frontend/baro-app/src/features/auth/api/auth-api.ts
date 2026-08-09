/** 로그인/회원가입 관련 API 래퍼. */
import { getJson, postJson } from '@/services/http-client';

import type { LoginRequest, LoginResult, SignupRequest, SignupResult, UserProfile } from './types';

/** POST /api/auth/login — 아이디/비밀번호로 로그인하고 토큰을 발급받는다. */
export function login(request: LoginRequest): Promise<LoginResult> {
  return postJson<LoginResult>('/api/auth/login', request);
}

/** GET /api/users/me — 저장된 토큰으로 세션을 복원할 때 내 프로필을 조회한다. */
export function getMyProfile(accessToken: string): Promise<UserProfile> {
  return getJson<UserProfile>('/api/users/me', accessToken);
}

/** POST /api/auth/signup — 계정을 생성한다. 성공해도 토큰은 내려오지 않아 자동 로그인은 하지 않는다. */
export function signup(request: SignupRequest): Promise<SignupResult> {
  return postJson<SignupResult>('/api/auth/signup', request);
}
