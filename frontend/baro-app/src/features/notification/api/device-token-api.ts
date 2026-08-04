import { postJson } from '@/services/http-client';

export type DevicePlatform = 'ANDROID' | 'IOS';

export type RegisterDeviceTokenRequest = {
  token: string;
  platform: DevicePlatform;
};

const DEVICE_TOKENS_PATH = '/api/users/me/device-tokens';

export function registerDeviceToken(
  request: RegisterDeviceTokenRequest,
  accessToken: string,
): Promise<void> {
  return postJson<void>(DEVICE_TOKENS_PATH, request, accessToken);
}
