/** 내 프로필 수정/회원 탈퇴 API 래퍼. */
import { patchJson, postJson } from '@/services/http-client';

import type {
  UpdateMyProfileRequest,
  UpdateMyProfileResult,
  WithdrawAccountRequest,
  WithdrawAccountResult,
} from './types';

/** PATCH /api/users/me — 내 프로필(이름, 연락처 등)을 수정한다. */
export function updateMyProfile(
  request: UpdateMyProfileRequest,
  accessToken: string,
): Promise<UpdateMyProfileResult> {
  return patchJson<UpdateMyProfileResult>('/api/users/me', request, accessToken);
}

/** POST /api/users/me/withdrawal — 회원 탈퇴를 요청한다. */
export function withdrawMyAccount(
  request: WithdrawAccountRequest,
  accessToken: string,
): Promise<WithdrawAccountResult> {
  return postJson<WithdrawAccountResult>('/api/users/me/withdrawal', request, accessToken);
}
