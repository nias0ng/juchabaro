import { Text, View } from 'react-native';

import { useCountdown } from '@/features/move-request/hooks/use-countdown';
import type { VehicleStatusDisplay } from '../utils/parking-session';

import { styles } from './vehicle-status-card.styles';

type VehicleStatusCardProps = {
  session: VehicleStatusDisplay | null;
  pageLabel?: string;
  contained?: boolean;
  isLoading?: boolean;
  hasError?: boolean;
};

const EV_WARNING_THRESHOLD_MS = 60 * 60_000;

function formatEvRemainingTime(remainingMs: number): string {
  const isOverdue = remainingMs <= 0;
  const absoluteMs = Math.abs(remainingMs);
  if (isOverdue && absoluteMs < 60_000) return '1분 미만 경과';

  const totalMinutes = Math.max(1, Math.floor(absoluteMs / 60_000));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  const suffix = isOverdue ? '경과' : '남음';

  if (hours === 0) return `${minutes}분 ${suffix}`;
  if (minutes === 0) return `${hours}시간 ${suffix}`;
  return `${hours}시간 ${minutes}분 ${suffix}`;
}

export function VehicleStatusCard({
  session,
  pageLabel,
  contained = false,
  isLoading = false,
  hasError = false,
}: VehicleStatusCardProps) {
  const countdown = useCountdown(session?.dueAt ?? null);

  if (isLoading || hasError || !session) {
    const statusMessage = isLoading
      ? '주차 정보를 불러오는 중입니다'
      : hasError
        ? '주차 정보를 불러오지 못했습니다'
        : '주차된 차량이 없습니다';

    return (
      <View style={[styles.card, styles.emptyCard]}>
        <Text style={styles.emptyText}>{statusMessage}</Text>
      </View>
    );
  }

  const isViolation = session.status === 'VIOLATION';
  const isEvTimeWarning = session.isEvCharging && countdown.remainingMs <= EV_WARNING_THRESHOLD_MS;

  return (
    <View style={[styles.card, contained && styles.cardContained]}>
      <View style={styles.headerGroup}>
        <View style={styles.statusRow}>
          <View style={[styles.statusDot, isViolation && styles.statusDotViolation]} />
          <Text style={[styles.statusLabel, isViolation && styles.statusLabelViolation]}>
            {session.statusLabel}
          </Text>
          <Text style={styles.statusTime}>{session.statusTime}</Text>
        </View>

        <View style={styles.plateRow}>
          <Text style={styles.plateText}>{session.plateNumber}</Text>
          {session.model ? <Text style={styles.modelText}>{session.model}</Text> : null}
        </View>
      </View>

      <View style={styles.detailsRow}>
        <View style={styles.detailColumn}>
          <Text style={styles.fieldLabel}>위치</Text>
          <Text style={styles.fieldValue}>{session.location}</Text>
        </View>

        {session.isEvCharging ? (
          <View style={styles.detailColumn}>
            <Text style={styles.fieldLabel}>
              {countdown.isOverdue ? '충전 시간 초과' : '충전 종료까지'}
            </Text>
            <Text style={[styles.fieldValue, isEvTimeWarning && styles.fieldValueWarning]}>
              {formatEvRemainingTime(countdown.remainingMs)}
            </Text>
          </View>
        ) : null}

        {pageLabel ? <Text style={styles.pageIndicatorText}>{pageLabel}</Text> : null}
      </View>
    </View>
  );
}
