/** 푸시 알림 발송 대상을 결정하는 디바이스 토큰 등록/해제 API 래퍼. */
import { deleteJson, postJson } from '@/services/http-client';

export type DevicePlatform = 'ANDROID' | 'IOS';

export type RegisterDeviceTokenRequest = {
  token: string;
  platform: DevicePlatform;
};

const DEVICE_TOKENS_PATH = '/api/users/me/device-tokens';

/** POST /api/users/me/device-tokens — 이 기기의 푸시 토큰을 내 계정에 등록한다. */
export function registerDeviceToken(
  request: RegisterDeviceTokenRequest,
  accessToken: string,
): Promise<void> {
  return postJson<void>(DEVICE_TOKENS_PATH, request, accessToken);
}

/** DELETE /api/users/me/device-tokens — 로그아웃 등으로 더 이상 쓰지 않는 푸시 토큰을 해제한다. */
export function unregisterDeviceToken(
  request: RegisterDeviceTokenRequest,
  accessToken: string,
): Promise<void> {
  return deleteJson<void>(DEVICE_TOKENS_PATH, accessToken, request);
}
