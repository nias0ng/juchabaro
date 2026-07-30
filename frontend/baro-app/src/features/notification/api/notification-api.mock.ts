import type { NotificationListResult } from './types';

const MOCK_RESPONSE_DELAY_MS = 400;

function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

function hoursAgo(hours: number): string {
  return minutesAgo(hours * 60);
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Figma F-01 카드 구성 기준. requestId 201은 move-request-api.mock.ts의 mockRequestDetail과 동일하게 맞춰서
// 알림 클릭 -> E-11 상세 -> 응답 -> F-02 흐름을 목 데이터만으로 이어서 확인할 수 있게 한다.
export async function getNotificationsMock(): Promise<NotificationListResult> {
  await delay(MOCK_RESPONSE_DELAY_MS);

  const notifications = [
    {
      notificationId: 1001,
      eventId: 101,
      requestId: 201,
      notificationType: 'MOVE_REQUEST' as const,
      title: '차량 이동 요청이 도착했습니다',
      body: '주차 상태를 확인하고 차량을 이동해 주세요.',
      sentAt: minutesAgo(0),
    },
    {
      notificationId: 1002,
      eventId: 102,
      requestId: 201,
      notificationType: 'REMINDER' as const,
      title: '이동 요청 1차 재알림을 보냈습니다',
      body: '아직 확인되지 않아 다시 알려드립니다.',
      sentAt: minutesAgo(3),
    },
    {
      notificationId: 1003,
      eventId: 103,
      requestId: null,
      notificationType: 'EV_OVERSTAY' as const,
      title: '충전구역 이용 시간이 곧 종료됩니다',
      body: '15분 뒤부터 초과 주차로 기록됩니다.',
      sentAt: minutesAgo(10),
    },
    {
      notificationId: 1004,
      eventId: 104,
      requestId: 198,
      notificationType: 'EVENT_RESOLVED' as const,
      title: '요청하신 차량이 이동되었습니다',
      body: '요청 #198이 종료되었습니다.',
      sentAt: hoursAgo(27),
    },
  ];

  return {
    notifications,
    page: 0,
    size: 20,
    totalElements: notifications.length,
    totalPages: 1,
  };
}
