import { Text, View } from 'react-native';

import { Stack } from '@/components/ui';
import { useCountdown } from '@/features/move-request/hooks/use-countdown';
import type { VehicleStatusDisplay } from '../utils/parking-session';
import { Spacing } from '@/styles';

import { styles } from './vehicle-status-card.styles';

type VehicleStatusCardProps = {
  session: VehicleStatusDisplay | null;
  additionalCount?: number;
  isLoading?: boolean;
  hasError?: boolean;
};

const EV_WARNING_THRESHOLD_MS = 60 * 60_000;

function formatEvRemainingTime(remainingMs: number): string {
  if (remainingMs <= 0) return '이용 시간 초과';

  const totalMinutes = Math.max(1, Math.ceil(remainingMs / 60_000));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;

  if (hours === 0) return `${minutes}분 남음`;
  if (minutes === 0) return `${hours}시간 남음`;
  return `${hours}시간 ${minutes}분 남음`;
}

export function VehicleStatusCard({
  session,
  additionalCount = 0,
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
    <View style={styles.card}>
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

      <Stack gap={Spacing.xxs}>
        <Text style={styles.fieldLabel}>위치</Text>
        <Text style={styles.fieldValue}>{session.location}</Text>
      </Stack>

      {session.isEvCharging ? (
        <View style={[styles.evTimeBox, isEvTimeWarning && styles.evTimeBoxWarning]}>
          <Text style={styles.evTimeLabel}>충전구역 이용 종료까지</Text>
          <Text style={[styles.evTimeValue, isEvTimeWarning && styles.evTimeValueWarning]}>
            {formatEvRemainingTime(countdown.remainingMs)}
          </Text>
        </View>
      ) : null}

      {additionalCount > 0 ? (
        <Text style={styles.additionalCountBadge}>+{additionalCount}대 더 주차 중</Text>
      ) : null}
    </View>
  );
}
