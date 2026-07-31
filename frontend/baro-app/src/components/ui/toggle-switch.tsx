import { Pressable, View } from 'react-native';

import { styles } from './toggle-switch.styles';

type ToggleSwitchProps = {
  value: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
};

/** 알림 설정(I-04)/차량 등록(G-01,G-02)이 함께 쓰는 공통 온오프 스위치. */
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
