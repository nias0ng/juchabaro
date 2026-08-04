import { useEffect, useRef } from 'react';

import { registerDeviceToken } from '@/features/notification/api/device-token-api';
import { getPushTokenRegistration } from '@/features/notification/services/push-token';
import { useAuth } from '@/providers/auth-provider';

export function usePushTokenRegistration(): void {
  const { accessToken, status, user } = useAuth();
  const attemptedAccessTokenRef = useRef<string | null>(null);

  useEffect(() => {
    if (status !== 'authenticated' || !accessToken || user?.role !== 'RESIDENT') {
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
        if (!registration || cancelled) {
          return;
        }

        await registerDeviceToken(registration, accessToken);
      } catch (error) {
        if (__DEV__) {
          console.warn('푸시 알림 토큰을 등록하지 못했습니다.', error);
        }
      }
    };

    void register();

    return () => {
      cancelled = true;
    };
  }, [accessToken, status, user?.role]);
}
