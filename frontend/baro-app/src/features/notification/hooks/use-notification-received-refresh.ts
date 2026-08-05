import { useQueryClient } from '@tanstack/react-query';
import * as Notifications from 'expo-notifications';
import { useEffect } from 'react';
import { Platform } from 'react-native';

import { useAuth } from '@/providers/auth-provider';

import { invalidateForNotification } from '../utils/notification-cache';

/** 앱이 열려 있는 동안 푸시를 받으면 알림 타입에 맞는 관련 쿼리만 즉시 무효화한다. */
export function useNotificationReceivedRefresh(): void {
  const { status } = useAuth();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (Platform.OS === 'web' || status !== 'authenticated') return;

    const subscription = Notifications.addNotificationReceivedListener((event) => {
      invalidateForNotification(queryClient, event.request.content.data);
    });
    return () => subscription.remove();
  }, [status, queryClient]);
}
