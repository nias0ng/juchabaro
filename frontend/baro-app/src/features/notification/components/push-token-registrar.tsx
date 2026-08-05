import { useEffect } from 'react';

import { useNotificationResponseNavigation } from '@/features/notification/hooks/use-notification-response-navigation';
import { usePushTokenRegistration } from '@/features/notification/hooks/use-push-token-registration';
import { configureForegroundNotificationPresentation } from '@/features/notification/services/notification-presentation';

export function PushTokenRegistrar() {
  useEffect(() => {
    configureForegroundNotificationPresentation();
  }, []);

  usePushTokenRegistration();
  useNotificationResponseNavigation();
  return null;
}
