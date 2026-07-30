import { Pressable, Text, View } from 'react-native';

import { styles } from './request-list-card.styles';

export type RequestListStatus = 'RESPONDED' | 'PENDING' | 'CLOSED';

export type RequestListItemDisplay = {
  requestId: number;
  status: RequestListStatus;
  timestampLabel: string;
  plateNumber: string;
  situationLabel: string;
  // 상태별로 하나만 채워진다: RESPONDED는 카운트다운, CLOSED는 소요시간 문구.
  countdownLabel?: string;
  closedSummary?: string;
};

const STATUS_LABEL: Record<RequestListStatus, string> = {
  RESPONDED: '응답 완료',
  PENDING: '응답 대기',
  CLOSED: '종료',
};

const STATUS_BADGE_STYLE: Record<RequestListStatus, { badge: object; text: object }> = {
  RESPONDED: { badge: styles.badgeResponded, text: styles.badgeTextResponded },
  PENDING: { badge: styles.badgePending, text: styles.badgeTextPending },
  CLOSED: { badge: styles.badgeClosed, text: styles.badgeTextClosed },
};

type RequestListCardProps = {
  item: RequestListItemDisplay;
  /** 없으면 눌러도 아무 데도 이동하지 않는다(보낸 요청은 아직 상세 화면이 없음). */
  onPress?: () => void;
};

export function RequestListCard({ item, onPress }: RequestListCardProps) {
  const badgeStyle = STATUS_BADGE_STYLE[item.status];

  return (
    <Pressable
      accessibilityRole="button"
      disabled={!onPress}
      style={[styles.card, item.status === 'RESPONDED' && styles.cardResponded]}
      onPress={onPress}
    >
      <View style={styles.topRow}>
        <View style={[styles.badge, badgeStyle.badge]}>
          <Text style={[styles.badgeText, badgeStyle.text]}>{STATUS_LABEL[item.status]}</Text>
        </View>
        <Text style={styles.timestamp}>{item.timestampLabel}</Text>
      </View>

      <View style={styles.plateRow}>
        <Text style={styles.plate}>{item.plateNumber}</Text>
        <Text style={styles.situation}>{item.situationLabel}</Text>
      </View>

      {item.countdownLabel ? (
        <View style={styles.countdownBox}>
          <Text style={styles.countdownMessage}>30분 이내 이동 예정</Text>
          <Text style={styles.countdownValue}>{item.countdownLabel}</Text>
        </View>
      ) : null}

      {item.closedSummary ? <Text style={styles.closedSummary}>{item.closedSummary}</Text> : null}
    </Pressable>
  );
}
