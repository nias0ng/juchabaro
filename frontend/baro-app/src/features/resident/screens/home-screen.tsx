import { ResponsiveContainer, Screen, Stack, ThemedText } from '@/components/ui';
import { Spacing } from '@/styles';

export default function HomeScreen() {
  return (
    <Screen edges={['top', 'right', 'left']}>
      <ResponsiveContainer>
        <Stack fill align="center" justify="center" gap={Spacing.md}>
          <ThemedText type="subtitle">주차바로</ThemedText>
          <ThemedText themeColor="textSecondary">입주민 홈 화면</ThemedText>
        </Stack>
      </ResponsiveContainer>
    </Screen>
  );
}
