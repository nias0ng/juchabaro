import { router } from 'expo-router';

import { ResponsiveContainer, Screen, Stack, ThemedText } from '@/components/ui';
import { useAuth } from '@/providers/auth-provider';
import { Spacing } from '@/styles';

import { MyPageView } from '../components/my-page-view';

export default function MyPageScreen() {
  const { user } = useAuth();

  return (
    <Screen scroll edges={['top', 'right', 'left']}>
      <ResponsiveContainer>
        <Stack gap={Spacing.xl}>
          <ThemedText type="subtitle">내 정보</ThemedText>
          <MyPageView
            nickname={user?.nickname ?? ''}
            onNavigateToVehicles={() => router.push('/resident/vehicles')}
          />
        </Stack>
      </ResponsiveContainer>
    </Screen>
  );
}
