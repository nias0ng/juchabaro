export type NotificationChannel = 'PUSH' | 'PUSH_SMS';

// PATCH /users/me/notification-settings 백엔드가 아직 없어 화면 로컬 상태 모양만 미리 정의해 둔다.
export type NotificationSettings = {
  moveRequestReceive: boolean; // 끌 수 없는 필수 알림. 항상 true.
  responseReminder: boolean;
  evOverstay: boolean;
  officeNotice: boolean;
  quietHoursStart: string;
  quietHoursEnd: string;
  channel: NotificationChannel;
};
