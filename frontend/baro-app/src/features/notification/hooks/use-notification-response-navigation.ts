import { useEffect, useRef } from 'react';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { navigateFromNotification } from '@/features/notification/utils/notification-navigation';
import { useAuth } from '@/providers/auth-provider';

export function useNotificationResponseNavigation(): void {
  const { status, user } = useAuth();
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
  }, [status, user?.role]);
}
