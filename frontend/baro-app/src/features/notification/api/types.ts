export type NotificationType =
  | 'MOVE_REQUEST'
  | 'MOVE_RESPONSE'
  | 'REMINDER'
  | 'EV_OVERSTAY'
  | 'EVENT_RESOLVED';

// GET /notifications 응답의 result.notifications 항목.
export type NotificationSummary = {
  notificationId: number;
  eventId: number | null;
  requestId: number | null;
  notificationType: NotificationType;
  title: string;
  body: string;
  sentAt: string;
};

// GET /notifications 응답의 result.
export type NotificationListResult = {
  notifications: NotificationSummary[];
  page: number;
  size: number;
  totalElements: number;
  totalPages: number;
};
