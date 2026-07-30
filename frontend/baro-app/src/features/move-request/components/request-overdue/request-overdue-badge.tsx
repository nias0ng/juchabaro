import { Text, View } from 'react-native';

import { styles } from './request-overdue-badge.styles';

export function RequestOverdueBadge() {
  return (
    <View style={styles.badge}>
      <Text style={styles.icon}>⚠</Text>
    </View>
  );
}
