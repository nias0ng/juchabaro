import { ResponsiveContainer, Screen, Stack, ThemedText } from '@/components/ui';
import { Spacing } from '@/styles';

export default function RequestsScreen() {
  return (
    <Screen edges={['top', 'right', 'left']}>
      <ResponsiveContainer>
        <Stack fill align="center" justify="center" gap={Spacing.md}>
          <ThemedText type="subtitle">요청</ThemedText>
          <ThemedText themeColor="textSecondary">받은 이동 요청과 보낸 요청을 확인합니다.</ThemedText>
        </Stack>
      </ResponsiveContainer>
    </Screen>
  );
}
