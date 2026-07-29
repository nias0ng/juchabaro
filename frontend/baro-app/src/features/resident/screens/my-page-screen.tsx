import { ResponsiveContainer, Screen, Stack, ThemedText } from '@/components/ui';
import { Spacing } from '@/styles';

export default function MyPageScreen() {
  return (
    <Screen edges={['top', 'right', 'left']}>
      <ResponsiveContainer>
        <Stack fill align="center" justify="center" gap={Spacing.md}>
          <ThemedText type="subtitle">내 정보</ThemedText>
          <ThemedText themeColor="textSecondary">사용자 정보와 로그아웃을 관리합니다.</ThemedText>
        </Stack>
      </ResponsiveContainer>
    </Screen>
  );
}
