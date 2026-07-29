import { ResponsiveContainer, Screen, Stack, ThemedText } from '@/components/ui';
import { Spacing } from '@/styles';

export default function NotificationsScreen() {
  return (
    <Screen edges={['top', 'right', 'left']}>
      <ResponsiveContainer>
        <Stack fill align="center" justify="center" gap={Spacing.md}>
          <ThemedText type="subtitle">알림</ThemedText>
          <ThemedText themeColor="textSecondary">이동 요청과 주차 알림을 표시합니다.</ThemedText>
        </Stack>
      </ResponsiveContainer>
    </Screen>
  );
}
