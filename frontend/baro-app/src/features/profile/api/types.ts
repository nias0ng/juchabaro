import type { UserProfile } from '@/features/auth/api/types';

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
