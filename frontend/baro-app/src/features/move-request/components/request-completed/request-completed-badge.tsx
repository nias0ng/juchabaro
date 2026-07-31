import { LinearGradient } from 'expo-linear-gradient';
import { Text, View } from 'react-native';

import { styles } from './request-completed-badge.styles';

const CHECK_GRADIENT = ['#6fcfc4', '#8b7ff0'] as const;

export function RequestCompletedBadge() {
  return (
    <View style={styles.outer}>
      <LinearGradient colors={CHECK_GRADIENT} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.inner}>
        <Text style={styles.check}>✓</Text>
      </LinearGradient>
    </View>
  );
}
