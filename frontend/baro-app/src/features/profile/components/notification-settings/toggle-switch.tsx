import { Pressable, View } from 'react-native';

import { styles } from './toggle-switch.styles';

type ToggleSwitchProps = {
  value: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
};

export function ToggleSwitch({ value, onChange, disabled = false }: ToggleSwitchProps) {
  return (
    <Pressable
      accessibilityRole="switch"
      accessibilityState={{ checked: value, disabled }}
      disabled={disabled}
      hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
      style={[
        styles.track,
        value && styles.trackOn,
        disabled && value && styles.trackOnDisabled,
        value ? styles.thumbAlignEnd : styles.thumbAlignStart,
      ]}
      onPress={() => onChange(!value)}
    >
      <View style={styles.thumb} />
    </Pressable>
  );
}
