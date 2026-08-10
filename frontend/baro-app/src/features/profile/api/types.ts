import type { UserProfile } from '@/features/auth/api/types';

// GET /api/users/me/notification-settings에서 화면이 실제로 사용하는 설정.
export type NotificationSettings = {
  moveRequestReceive: boolean; // 끌 수 없는 필수 알림. 항상 true.
  responseReminder: boolean;
  evOverstay: boolean;
  quietHoursStart: string;
  quietHoursEnd: string;
};

// PATCH는 변경한 항목만 보내며, 필수 이동 요청 알림은 수정 대상에서 제외한다.
export type UpdateNotificationSettingsRequest = Partial<
  Pick<NotificationSettings, 'responseReminder' | 'evOverstay' | 'quietHoursStart' | 'quietHoursEnd'>
>;

// PATCH /api/users/me 요청. 이름과 새 비밀번호 중 하나 이상을 전달한다.
export type UpdateMyProfileRequest = {
  name?: string;
  currentPassword?: string;
  newPassword?: string;
};

// 수정 성공 응답은 GET /api/users/me와 같은 사용자 정보 구조다.
export type UpdateMyProfileResult = UserProfile;

// POST /api/users/me/withdrawal 요청.
export type WithdrawAccountRequest = {
  currentPassword: string;
};

export type WithdrawAccountResult = {
  userId: number;
  status: 'DELETED';
  withdrawnAt: string;
};
