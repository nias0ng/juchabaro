import { Pressable, Text, View } from 'react-native';

import { useCountdown } from '@/features/move-request/hooks/use-countdown';
import { formatMinutesLabel } from '@/features/move-request/utils/move-request';

import { RequestStatusBadge, type RequestListStatus } from './request-status-badge';
import { styles } from './request-list-card.styles';

export type { RequestListStatus };

export type RequestListItemDisplay = {
  requestId: number;
  status: RequestListStatus;
  timestampLabel: string;
  plateNumber: string;
  situationLabel: string;
  closedSummary?: string;
  // RESPONDED일 때만 채워진다. dueAt이 있어야 카운트다운 박스를 보여준다.
  dueAt?: string | null;
  estimatedMinutes?: number | null;
};

type RequestListCardProps = {
  item: RequestListItemDisplay;
  /** 읽기 전용 진행 현황 또는 응답 가능한 상세 화면으로 이동할 때 사용한다. */
  onPress?: () => void;
};

export function RequestListCard({ item, onPress }: RequestListCardProps) {
  return (
    <Pressable
      accessibilityRole="button"
      disabled={!onPress}
      style={[styles.card, item.status === 'RESPONDED' && styles.cardResponded]}
      onPress={onPress}
    >
      <View style={styles.topRow}>
        <RequestStatusBadge status={item.status} />
        <Text style={styles.timestamp}>{item.timestampLabel}</Text>
      </View>

      <View style={styles.plateBlock}>
        <Text style={styles.plate}>{item.plateNumber}</Text>
        <Text style={styles.situation}>{item.situationLabel}</Text>
      </View>

      {item.status === 'RESPONDED' && item.dueAt ? (
        <RequestListCountdownBox dueAt={item.dueAt} estimatedMinutes={item.estimatedMinutes ?? null} />
      ) : null}

      {item.closedSummary ? <Text style={styles.closedSummary}>{item.closedSummary}</Text> : null}
    </Pressable>
  );
}

type RequestListCountdownBoxProps = {
  dueAt: string;
  estimatedMinutes: number | null;
};

// 카드 여러 개가 각자 다른 dueAt으로 매초 갱신되어야 해서, 카운트다운은 카드 안에서 직접 계산한다.
// 진행률 링(progress)은 목록 카드에서 쓰지 않으므로 startAt(respondedAt)은 넘기지 않는다.
function RequestListCountdownBox({ dueAt, estimatedMinutes }: RequestListCountdownBoxProps) {
  const countdown = useCountdown(dueAt);
  const message = estimatedMinutes ? `${formatMinutesLabel(estimatedMinutes)} 이내 이동 예정` : '이동 예정';

  return (
    <View style={styles.countdownBox}>
      <Text style={styles.countdownMessage}>{message}</Text>
      <Text style={styles.countdownValue}>{countdown.isOverdue ? '약속 시간 경과' : `${countdown.label} 남음`}</Text>
    </View>
  );
}
