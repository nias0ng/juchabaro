import { useEffect } from 'react';

import { useNotificationResponseNavigation } from '@/features/notification/hooks/use-notification-response-navigation';
import { useNotificationReceivedRefresh } from '@/features/notification/hooks/use-notification-received-refresh';
import { usePushTokenRegistration } from '@/features/notification/hooks/use-push-token-registration';
import { configureForegroundNotificationPresentation } from '@/features/notification/services/notification-presentation';

export function PushTokenRegistrar() {
  useEffect(() => {
    configureForegroundNotificationPresentation();
  }, []);

  usePushTokenRegistration();
  useNotificationReceivedRefresh();
  useNotificationResponseNavigation();
  return null;
}
