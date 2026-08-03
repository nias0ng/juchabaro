import { patchJson, postJson } from '@/services/http-client';

import type {
  UpdateMyProfileRequest,
  UpdateMyProfileResult,
  WithdrawAccountRequest,
  WithdrawAccountResult,
} from './types';

export function updateMyProfile(
  request: UpdateMyProfileRequest,
  accessToken: string,
): Promise<UpdateMyProfileResult> {
  return patchJson<UpdateMyProfileResult>('/api/users/me', request, accessToken);
}

export function withdrawMyAccount(
  request: WithdrawAccountRequest,
  accessToken: string,
): Promise<WithdrawAccountResult> {
  return postJson<WithdrawAccountResult>('/api/users/me/withdrawal', request, accessToken);
}
