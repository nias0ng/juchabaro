import { StyleSheet } from 'react-native';

import { ThemedText } from '@/components/ui/themed-text';
import { ThemedView } from '@/components/ui/themed-view';
import { Spacing } from '@/constants/theme';

export default function VehiclesScreen() {
  return (
    <ThemedView style={styles.container}>
      <ThemedText type="subtitle">차량</ThemedText>
      <ThemedText themeColor="textSecondary">등록 차량을 관리합니다.</ThemedText>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.three,
    padding: Spacing.four,
  },
});
