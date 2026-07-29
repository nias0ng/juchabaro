import { LinearGradient } from 'expo-linear-gradient';
import { router } from 'expo-router';
import { Text } from 'react-native';

import { ResponsiveContainer, Screen } from '@/components/ui';
import { HomeTopBar } from '@/features/resident/components/home-top-bar';
import { ParkingStatusCard } from '@/features/resident/components/parking-status-card';
import { QuickActionGrid, type QuickAction } from '@/features/resident/components/quick-action-grid';
import { VehicleStatusCard } from '@/features/resident/components/vehicle-status-card';
import { useParkingSessions } from '@/features/resident/hooks/use-parking-sessions';
import { useParkingZoneSummary } from '@/features/resident/hooks/use-parking-zone-summary';
import { pickPrimarySession, toVehicleStatusDisplay } from '@/features/resident/utils/parking-session';
import { toParkingStatusDisplay } from '@/features/resident/utils/parking-zone';
import { useAuth } from '@/providers/auth-provider';
import { Palette } from '@/styles';

import { styles } from './home-screen.styles';

const DEFAULT_AVATAR_INITIAL = '바';
const DEFAULT_UNIT_LABEL = '동/호수 정보 없음';
const PARKING_STATUS_TITLE = '주차 현황 · 지하 1층';

const quickActions: QuickAction[] = [
  {
    label: '이동\n요청',
    background: Palette.mint100,
    iconColor: Palette.emerald500,
    onPress: () => router.push('/resident/requests'),
  },
  {
    label: '내\n차량',
    background: Palette.lavender100,
    iconColor: Palette.violet500,
    onPress: () => router.push('/resident/vehicles'),
  },
  { label: '방문\n등록', background: Palette.peach100, iconColor: Palette.orange400 },
  { label: '위반\n이력', background: Palette.sky100, iconColor: Palette.blue500 },
];

export default function HomeScreen() {
  const { user } = useAuth();
  const avatarInitial = user?.nickname?.trim().charAt(0) || DEFAULT_AVATAR_INITIAL;
  // 관리자 계정 등 동/호수가 없는 경우(buildingNumber/unitNumber가 null) 대비.
  const unitLabel =
    user?.buildingNumber && user?.unitNumber
      ? `${user.buildingNumber}동 ${user.unitNumber}호`
      : DEFAULT_UNIT_LABEL;

  const {
    sessions,
    isLoading: isSessionsLoading,
    error: sessionsError,
  } = useParkingSessions();
  const primarySession = pickPrimarySession(sessions);
  const vehicleStatus = primarySession ? toVehicleStatusDisplay(primarySession) : null;
  const additionalSessionCount = Math.max(sessions.length - 1, 0);
  const mySpotCodes = sessions.map((session) => session.spotCode);

  const {
    summary,
    isLoading: isSummaryLoading,
    error: summaryError,
  } = useParkingZoneSummary();
  const parkingStatus = summary ? toParkingStatusDisplay(summary, mySpotCodes) : null;

  return (
    <LinearGradient
      colors={['#ddf3f0', '#eae7fb', '#f7f6fb']}
      locations={[0, 0.46, 0.78]}
      style={styles.gradient}
    >
      <Screen scroll edges={['top', 'right', 'left']} backgroundColor="transparent">
        <ResponsiveContainer style={styles.content}>
          <HomeTopBar
            unitLabel={unitLabel}
            avatarInitial={avatarInitial}
            onPressNotification={() => router.push('/resident/notifications')}
          />

          <Text style={styles.greeting}>{'주차, 오늘도\n편안하게'}</Text>

          <QuickActionGrid actions={quickActions} />

          <VehicleStatusCard
            session={vehicleStatus}
            additionalCount={additionalSessionCount}
            isLoading={isSessionsLoading}
            hasError={Boolean(sessionsError)}
          />

          <ParkingStatusCard
            title={PARKING_STATUS_TITLE}
            status={parkingStatus}
            isLoading={isSummaryLoading}
            hasError={Boolean(summaryError)}
          />

        </ResponsiveContainer>
      </Screen>
    </LinearGradient>
  );
}
