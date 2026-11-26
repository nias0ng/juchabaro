import { Pressable, Text, View } from 'react-native';
import { useThemedStyles } from '@/hooks/use-themed-styles';

import { createStyles } from './request-time-actions.styles';

type RequestTimeActionsProps = {
  onPressImmediate?: () => void;
  onPress30Min?: () => void;
  onPress60Min?: () => void;
  onPressDecline?: () => void;
  disabled?: boolean;
};

export function RequestTimeActions({
  onPressImmediate,
  onPress30Min,
  onPress60Min,
  onPressDecline,
  disabled = false,
}: RequestTimeActionsProps) {
  const styles = useThemedStyles(createStyles);
  return (
    <View style={[styles.container, disabled && styles.containerDisabled]}>
      <Text style={styles.heading}>언제 이동하실 수 있나요?</Text>

      <Pressable
        accessibilityRole="button"
        style={styles.immediateButton}
        disabled={disabled}
        onPress={onPressImmediate}
      >
        <Text style={styles.immediateButtonText}>바로 이동하겠습니다</Text>
        <Text style={styles.immediateButtonArrow}>→</Text>
      </Pressable>

      <View style={styles.timedRow}>
        <Pressable
          accessibilityRole="button"
          style={styles.timedButton30}
          disabled={disabled}
          onPress={onPress30Min}
        >
          <Text style={styles.timedButton30Text}>30분 이내</Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          style={styles.timedButton60}
          disabled={disabled}
          onPress={onPress60Min}
        >
          <Text style={styles.timedButton60Text}>1시간 이내</Text>
        </Pressable>
      </View>

      <Pressable
        accessibilityRole="button"
        style={styles.declineLink}
        disabled={disabled}
        onPress={onPressDecline}
      >
        <Text style={styles.declineText}>지금은 이동이 어렵습니다</Text>
      </Pressable>
    </View>
  );
}
