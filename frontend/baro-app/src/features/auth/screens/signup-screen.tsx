import { ResponsiveContainer, Screen, Stack, ThemedText } from '@/components/ui';
import { Spacing } from '@/styles';

export default function SignupScreen() {
  return (
    <Screen>
      <ResponsiveContainer>
        <Stack fill align="center" justify="center" gap={Spacing.md}>
          <ThemedText type="subtitle">회원가입</ThemedText>
          <ThemedText themeColor="textSecondary">회원가입 화면을 구현할 예정입니다.</ThemedText>
        </Stack>
      </ResponsiveContainer>
    </Screen>
  );
}
