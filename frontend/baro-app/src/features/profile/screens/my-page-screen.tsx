import { router } from 'expo-router';

import { GradientScreenBackground, ResponsiveContainer, ScreenHeader, Stack } from '@/components/ui';
import { ProfileAccountActions } from '@/features/profile/components/profile-account-actions';
import { ProfileIcon } from '@/features/profile/components/profile-icon';
import { ProfileMenuRow } from '@/features/profile/components/profile-menu-row';
import { ProfileStatsRow } from '@/features/profile/components/profile-stats-row';
import { ProfileSummaryCard } from '@/features/profile/components/profile-summary-card';
import { VehicleShortcutCard } from '@/features/profile/components/vehicle-shortcut-card';
import { useVehicleSummary } from '@/features/profile/hooks/use-vehicle-summary';
import { useViolationStats } from '@/features/violation/hooks/use-violation-stats';
import { useAuth } from '@/providers/auth-provider';
import { Spacing } from '@/styles';

// PENDING/REJECTED은 이번 스코프의 로그인 흐름상 도달하지 않지만, 상태가 늘어나도 배지가 깨지지 않게 매핑해 둔다.
const STATUS_LABEL: Partial<Record<string, string>> = {
  ACTIVE: '승인 완료',
  PENDING: '승인 대기',
};

export default function MyPageScreen() {
  const { user } = useAuth();
  const { isLoading: isVehicleLoading, vehicleCount, primaryVehicle } = useVehicleSummary();
  const { stats: violationStats, isLoading: isViolationLoading } = useViolationStats();

  const meta = user?.buildingNumber && user?.unitNumber ? `${user.buildingNumber}동 ${user.unitNumber}호` : '';

  const vehicleSubtitle = isVehicleLoading
    ? '차량 정보를 불러오는 중입니다'
    : primaryVehicle
      ? `대표 차량 · ${primaryVehicle.vehicleModel ?? primaryVehicle.plateNumber}`
      : '등록된 차량이 없습니다';

  return (
    <GradientScreenBackground>
      <ResponsiveContainer>
        <ScreenHeader title="내 정보" showBackButton={false} />

        <Stack gap={Spacing.base + 2}>
          <ProfileSummaryCard
            name={user?.name ?? ''}
            meta={meta}
            statusLabel={user ? STATUS_LABEL[user.status] : undefined}
          />

          <ProfileStatsRow
            vehicleCount={vehicleCount}
            violationCount={violationStats?.totalCount ?? null}
            isViolationLoading={isViolationLoading}
            onPressVehicles={() => router.push('/resident/vehicles')}
            onPressViolations={() => router.push('/resident/violation-history')}
          />

          <VehicleShortcutCard
            subtitle={vehicleSubtitle}
            onPress={() => router.push('/resident/vehicles')}
          />

          <Stack gap={Spacing.sm + 2}>
            <ProfileMenuRow
              label="내 정보 수정"
              icon={<ProfileIcon name="user" size={20} />}
              onPress={() => router.push('/resident/profile-edit')}
            />
            <ProfileMenuRow
              label="알림 설정"
              icon={<ProfileIcon name="bell" size={20} />}
              onPress={() => router.push('/resident/notification-settings')}
            />
            <ProfileMenuRow
              label="요청 내역"
              icon={<ProfileIcon name="history" size={20} />}
              onPress={() => router.push('/resident/request-history')}
            />
          </Stack>

          <ProfileAccountActions />
        </Stack>
      </ResponsiveContainer>
    </GradientScreenBackground>
  );
}
