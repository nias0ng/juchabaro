import { useEffect, useRef } from 'react';
import { Platform } from 'react-native';

import {
  registerDeviceToken,
  unregisterDeviceToken,
} from '@/features/notification/api/device-token-api';
import { getPushTokenRegistration } from '@/features/notification/services/push-token';
import {
  getStoredPushTokenRegistration,
  savePushTokenRegistration,
} from '@/features/notification/services/push-token-storage';
import { useAuth } from '@/providers/auth-provider';

const PUSH_LOGS_ENABLED = __DEV__ || process.env.EXPO_PUBLIC_ENABLE_API_LOGS === 'true';

/**
 * 로그인한 입주민 기기의 Expo 푸시 토큰을 발급받아 서버에 등록하고, 토큰이 바뀌면 이전 토큰은 해제한다.
 * API: POST /api/users/me/device-tokens, DELETE /api/users/me/device-tokens
 */
export function usePushTokenRegistration(): void {
  const { accessToken, status, user } = useAuth();
  const attemptedAccessTokenRef = useRef<string | null>(null);

  useEffect(() => {
    if (
      Platform.OS === 'web' ||
      status !== 'authenticated' ||
      !accessToken ||
      user?.role !== 'RESIDENT'
    ) {
      attemptedAccessTokenRef.current = null;
      return;
    }

    if (attemptedAccessTokenRef.current === accessToken) {
      return;
    }
    attemptedAccessTokenRef.current = accessToken;

    let cancelled = false;

    const register = async () => {
      try {
        const registration = await getPushTokenRegistration();
        if (!registration || cancelled) return;

        await registerDeviceToken(registration, accessToken);
        if (cancelled) return;

        const previousRegistration = await getStoredPushTokenRegistration();
        await savePushTokenRegistration(registration);

        if (previousRegistration && previousRegistration.token !== registration.token) {
          try {
            await unregisterDeviceToken(previousRegistration, accessToken);
          } catch (error) {
            if (PUSH_LOGS_ENABLED) {
              console.warn('[PUSH] OLD_TOKEN_UNREGISTER_FAILED', error);
            }
          }
        }
      } catch (error) {
        if (PUSH_LOGS_ENABLED) {
          console.warn('[PUSH] TOKEN_REGISTRATION_FAILED', error);
        }
      }
    };

    void register();

    return () => {
      cancelled = true;
    };
  }, [accessToken, status, user?.role]);
}
