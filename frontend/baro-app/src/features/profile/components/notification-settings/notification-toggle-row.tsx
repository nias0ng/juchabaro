import { Text, View } from 'react-native';

import { ToggleSwitch } from './toggle-switch';
import { styles } from './notification-toggle-row.styles';

type NotificationToggleRowProps = {
  label: string;
  subtitle?: string;
  value: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
  bordered?: boolean;
};

export function NotificationToggleRow({
  label,
  subtitle,
  value,
  onChange,
  disabled = false,
  bordered = true,
}: NotificationToggleRowProps) {
  return (
    <View style={[styles.row, bordered && styles.rowBorder]}>
      <View style={styles.textGroup}>
        <Text style={styles.label}>{label}</Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
      <ToggleSwitch value={value} onChange={onChange} disabled={disabled} />
    </View>
  );
}
