import { StyleSheet } from 'react-native';

import { ThemedText } from '@/components/ui/themed-text';
import { ThemedView } from '@/components/ui/themed-view';
import { Spacing } from '@/constants/theme';

export default function MyPageScreen() {
  return (
    <ThemedView style={styles.container}>
      <ThemedText type="subtitle">마이페이지</ThemedText>
      <ThemedText themeColor="textSecondary">사용자 정보와 로그아웃을 관리합니다.</ThemedText>
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
