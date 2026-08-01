import { getJson, postJson } from '@/services/http-client';

import type { LoginRequest, LoginResult, UserProfile } from './types';

// 관리자 계정은 README 기준 회원가입 없이 DB에 직접 생성되므로 signup은 admin-web에 두지 않는다.

export function login(request: LoginRequest): Promise<LoginResult> {
  return postJson<LoginResult>('/api/auth/login', request);
}

// 로그인 상태를 복원하거나 로그인 직후 상세 프로필을 채울 때 사용
export function getMyProfile(accessToken: string): Promise<UserProfile> {
  return getJson<UserProfile>('/api/users/me', accessToken);
}
