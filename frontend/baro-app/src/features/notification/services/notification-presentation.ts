import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

let isConfigured = false;

export function configureForegroundNotificationPresentation(): void {
  if (isConfigured || Platform.OS === 'web') {
    return;
  }

  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });

  isConfigured = true;
}
