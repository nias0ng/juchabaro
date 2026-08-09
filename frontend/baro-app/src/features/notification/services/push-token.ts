import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import type { DevicePlatform } from '../api/device-token-api';

/** 알림 권한을 요청하고 이 기기의 Expo 푸시 토큰을 발급받는다(웹/시뮬레이터는 null). */
export type PushTokenRegistration = {
  token: string;
  platform: DevicePlatform;
};

const ANDROID_NOTIFICATION_CHANNEL_ID = 'default';

function getProjectId(): string {
  const projectId = Constants.easConfig?.projectId ?? Constants.expoConfig?.extra?.eas?.projectId;

  if (!projectId) {
    throw new Error('EAS projectId가 설정되어 있지 않습니다.');
  }

  return projectId;
}

async function requestNotificationPermission(): Promise<boolean> {
  const currentPermission = await Notifications.getPermissionsAsync();
  if (currentPermission.status === Notifications.PermissionStatus.GRANTED) {
    return true;
  }

  const requestedPermission = await Notifications.requestPermissionsAsync();
  return requestedPermission.status === Notifications.PermissionStatus.GRANTED;
}

export async function getPushTokenRegistration(): Promise<PushTokenRegistration | null> {
  if (Platform.OS !== 'android' && Platform.OS !== 'ios') {
    return null;
  }

  if (!Device.isDevice) {
    return null;
  }

  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync(ANDROID_NOTIFICATION_CHANNEL_ID, {
      name: '기본 알림',
      importance: Notifications.AndroidImportance.MAX,
    });
  }

  const permissionGranted = await requestNotificationPermission();
  if (!permissionGranted) {
    return null;
  }

  const token = (
    await Notifications.getExpoPushTokenAsync({
      projectId: getProjectId(),
    })
  ).data;

  return {
    token,
    platform: Platform.OS === 'android' ? 'ANDROID' : 'IOS',
  };
}
