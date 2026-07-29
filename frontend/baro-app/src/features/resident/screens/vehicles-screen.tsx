import { ResponsiveContainer, Screen, Stack, ThemedText } from '@/components/ui';
import { Spacing } from '@/styles';

export default function VehiclesScreen() {
  return (
    <Screen edges={['top', 'right', 'left']}>
      <ResponsiveContainer>
        <Stack fill align="center" justify="center" gap={Spacing.md}>
          <ThemedText type="subtitle">차량</ThemedText>
          <ThemedText themeColor="textSecondary">등록 차량을 관리합니다.</ThemedText>
        </Stack>
      </ResponsiveContainer>
    </Screen>
  );
}
