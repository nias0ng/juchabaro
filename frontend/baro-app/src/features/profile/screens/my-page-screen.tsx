import { router } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, Text } from 'react-native';

import { IconGlyph, ResponsiveContainer, Screen, Stack } from '@/components/ui';
import { STROKE_ICON_PATHS } from '@/components/ui/bottom-nav-bar-icons';
import { ProfileMenuRow } from '@/features/profile/components/profile-menu-row';
import { ProfileStatsRow } from '@/features/profile/components/profile-stats-row';
import { ProfileSummaryCard } from '@/features/profile/components/profile-summary-card';
import { VehicleShortcutCard } from '@/features/profile/components/vehicle-shortcut-card';
import { useVehicleSummary } from '@/features/profile/hooks/use-vehicle-summary';
import { useAuth } from '@/providers/auth-provider';
import { Palette, Spacing } from '@/styles';

import { styles } from './my-page-screen.styles';

const ROLE_LABEL: Record<string, string> = {
  RESIDENT: '입주민',
  ADMIN: '관리자',
};

// PENDING/REJECTED은 이번 스코프의 로그인 흐름상 도달하지 않지만, 상태가 늘어나도 배지가 깨지지 않게 매핑해 둔다.
const STATUS_LABEL: Partial<Record<string, string>> = {
  ACTIVE: '승인 완료',
  PENDING: '승인 대기',
};

export default function MyPageScreen() {
  const { user, logout } = useAuth();
  const { isLoading: isVehicleLoading, vehicleCount, primaryVehicle } = useVehicleSummary();
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  const roleLabel = user ? (ROLE_LABEL[user.role] ?? user.role) : '';
  const meta = user?.buildingNumber && user?.unitNumber
    ? `${user.buildingNumber}동 ${user.unitNumber}호 · ${roleLabel}`
    : roleLabel;

  const vehicleSubtitle = isVehicleLoading
    ? '차량 정보를 불러오는 중입니다'
    : primaryVehicle
      ? `대표 차량 · ${primaryVehicle.carModel ?? primaryVehicle.plateNumber}`
      : '등록된 차량이 없습니다';

  const handleLogout = async () => {
    if (isLoggingOut) return;
    setIsLoggingOut(true);
    // 로그아웃 성공 시 status가 guest로 바뀌면서 resident/_layout.tsx의 가드가 자동으로 로그인 화면으로 보낸다.
    await logout();
  };

  return (
    <Screen scroll edges={['top', 'right', 'left']}>
      <ResponsiveContainer>
        <Stack gap={Spacing.base + 2}>
          <Text style={styles.title}>내 정보</Text>

          <ProfileSummaryCard
            name={user?.nickname ?? ''}
            meta={meta}
            statusLabel={user ? STATUS_LABEL[user.status] : undefined}
            onPress={() => router.push('/resident/profile-edit')}
          />

          <ProfileStatsRow vehicleCount={vehicleCount} />

          <VehicleShortcutCard subtitle={vehicleSubtitle} onPress={() => router.push('/resident/vehicles')} />

          <Stack gap={Spacing.sm + 2}>
            <ProfileMenuRow
              label="알림 설정"
              icon={<IconGlyph d={STROKE_ICON_PATHS.bell} size={18} color={Palette.gray975} />}
              onPress={() => router.push('/resident/notification-settings')}
            />
            <ProfileMenuRow label="요청 내역" onPress={() => router.push('/resident/request-history')} />
          </Stack>

          <Pressable
            accessibilityRole="button"
            accessibilityState={{ disabled: isLoggingOut, busy: isLoggingOut }}
            disabled={isLoggingOut}
            style={({ pressed }) => [styles.logoutButton, pressed && styles.logoutButtonPressed]}
            onPress={handleLogout}
          >
            {isLoggingOut ? (
              <ActivityIndicator color={Palette.red500} />
            ) : (
              <Text style={styles.logoutText}>로그아웃</Text>
            )}
          </Pressable>
        </Stack>
      </ResponsiveContainer>
    </Screen>
  );
}
