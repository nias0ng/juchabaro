import { Text, View } from 'react-native';

import { styles } from './request-countdown-ring.styles';

type RequestCountdownRingProps = {
  label: string;
};

export function RequestCountdownRing({ label }: RequestCountdownRingProps) {
  return (
    <View style={styles.ring}>
      <View style={styles.dial}>
        <Text style={styles.time}>{label}</Text>
        <Text style={styles.caption}>REMAINING</Text>
      </View>
    </View>
  );
}
