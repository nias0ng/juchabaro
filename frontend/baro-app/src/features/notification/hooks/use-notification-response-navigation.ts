import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { navigateFromNotification } from '@/features/notification/utils/notification-navigation';
import { useAuth } from '@/providers/auth-provider';

import { invalidateForNotification } from '../utils/notification-cache';

/** 사용자가 푸시 알림을 탭해서 앱을 열었을 때, 알림 데이터에 맞는 화면으로 이동시킨다. */
export function useNotificationResponseNavigation(): void {
  const { status, user } = useAuth();
  const queryClient = useQueryClient();
  const lastHandledIdentifierRef = useRef<string | null>(null);

  useEffect(() => {
    if (Platform.OS === 'web') return;

    let cancelled = false;

    const handleResponse = async (response: Notifications.NotificationResponse | null) => {
      if (
        cancelled ||
        !response ||
        status !== 'authenticated' ||
        user?.role !== 'RESIDENT'
      ) {
        return;
      }

      const identifier = response.notification.request.identifier;
      if (lastHandledIdentifierRef.current === identifier) return;

      lastHandledIdentifierRef.current = identifier;
      invalidateForNotification(queryClient, response.notification.request.content.data);
      navigateFromNotification(response.notification.request.content.data);
      await Notifications.clearLastNotificationResponseAsync();
    };

    const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
      void handleResponse(response);
    });

    void Notifications.getLastNotificationResponseAsync().then(handleResponse);

    return () => {
      cancelled = true;
      subscription.remove();
    };
  }, [status, user?.role, queryClient]);
}
