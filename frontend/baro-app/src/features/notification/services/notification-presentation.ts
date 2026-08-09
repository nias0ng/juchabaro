/** 앱이 포그라운드에 있을 때도 배너/배지로 푸시 알림이 보이도록 설정한다. */
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
