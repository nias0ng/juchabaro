import { Text, View } from 'react-native';

import { styles } from './request-status-badge.styles';

export type RequestListStatus = 'RESPONDED' | 'PENDING' | 'REMINDER' | 'ESCALATED' | 'CLOSED';

const STATUS_LABEL: Record<RequestListStatus, string> = {
  RESPONDED: '응답 완료',
  PENDING: '응답 대기',
  REMINDER: '재알림 발송',
  ESCALATED: '관리사무소 처리 중',
  CLOSED: '종료',
};

const STATUS_STYLE: Record<RequestListStatus, { badge: object; text: object }> = {
  RESPONDED: { badge: styles.badgeResponded, text: styles.textResponded },
  PENDING: { badge: styles.badgePending, text: styles.textPending },
  REMINDER: { badge: styles.badgeReminder, text: styles.textReminder },
  ESCALATED: { badge: styles.badgeEscalated, text: styles.textEscalated },
  CLOSED: { badge: styles.badgeClosed, text: styles.textClosed },
};

type RequestStatusBadgeProps = {
  status: RequestListStatus;
};

/** 요청 카드 상단의 상태 배지(응답 완료/응답 대기/종료). 상태별 색 매핑을 이 컴포넌트 하나로 관리한다. */
export function RequestStatusBadge({ status }: RequestStatusBadgeProps) {
  const style = STATUS_STYLE[status];

  return (
    <View style={[styles.badge, style.badge]}>
      <Text style={[styles.text, style.text]}>{STATUS_LABEL[status]}</Text>
    </View>
  );
}
