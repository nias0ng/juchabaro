import * as Notifications from 'expo-notifications';
import { useEffect } from 'react';
import { Platform } from 'react-native';

import { useAuth } from '@/providers/auth-provider';
import { refreshAuthenticatedQueries } from '@/services/authenticated-query-refresh';

/** 앱이 열려 있는 동안 푸시를 받으면 현재 화면의 관련 서버 조회를 즉시 갱신한다. */
export function useNotificationReceivedRefresh(): void {
  const { status } = useAuth();

  useEffect(() => {
    if (Platform.OS === 'web' || status !== 'authenticated') return;

    const subscription = Notifications.addNotificationReceivedListener(() => {
      refreshAuthenticatedQueries();
    });
    return () => subscription.remove();
  }, [status]);
}
