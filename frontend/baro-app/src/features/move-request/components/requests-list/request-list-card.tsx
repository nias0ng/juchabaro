import { Pressable, Text, View } from 'react-native';

import { RequestStatusBadge, type RequestListStatus } from './request-status-badge';
import { styles } from './request-list-card.styles';

export type { RequestListStatus };

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

type RequestListCardProps = {
  item: RequestListItemDisplay;
  /** 없으면 눌러도 아무 데도 이동하지 않는다(보낸 요청은 상세 화면으로 이동시키지 않는다). */
  onPress?: () => void;
};

export function RequestListCard({ item, onPress }: RequestListCardProps) {
  return (
    <Pressable
      accessibilityRole="button"
      disabled={!onPress}
      style={styles.card}
      onPress={onPress}
    >
      <View style={styles.topRow}>
        <RequestStatusBadge status={item.status} />
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
