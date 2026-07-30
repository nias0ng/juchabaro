import { Pressable, Text, View } from 'react-native';

import { styles } from './request-time-actions.styles';

type RequestTimeActionsProps = {
  onPressImmediate?: () => void;
  onPress10Min?: () => void;
  onPress30Min?: () => void;
  onPressDecline?: () => void;
};

export function RequestTimeActions({
  onPressImmediate,
  onPress10Min,
  onPress30Min,
  onPressDecline,
}: RequestTimeActionsProps) {
  return (
    <View style={styles.container}>
      <Text style={styles.heading}>언제 이동하실 수 있나요?</Text>

      <Pressable accessibilityRole="button" style={styles.immediateButton} onPress={onPressImmediate}>
        <Text style={styles.immediateButtonText}>바로 이동하겠습니다</Text>
        <Text style={styles.immediateButtonArrow}>→</Text>
      </Pressable>

      <View style={styles.timedRow}>
        <Pressable accessibilityRole="button" style={styles.timedButton10} onPress={onPress10Min}>
          <Text style={styles.timedButton10Text}>10분 이내</Text>
        </Pressable>
        <Pressable accessibilityRole="button" style={styles.timedButton30} onPress={onPress30Min}>
          <Text style={styles.timedButton30Text}>30분 이내</Text>
        </Pressable>
      </View>

      <Pressable accessibilityRole="button" style={styles.declineLink} onPress={onPressDecline}>
        <Text style={styles.declineText}>지금은 이동이 어렵습니다</Text>
      </Pressable>
    </View>
  );
}
