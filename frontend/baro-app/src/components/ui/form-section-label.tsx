import { Text } from 'react-native';

import { useThemedStyles } from '@/hooks/use-themed-styles';

import { createStyles } from './form-section-label.styles';

type FormSectionLabelVariant = 'default' | 'muted';

type FormSectionLabelProps = {
  label: string;
  suffix?: string;
  variant?: FormSectionLabelVariant;
};

export function FormSectionLabel({ label, suffix, variant = 'default' }: FormSectionLabelProps) {
  const styles = useThemedStyles(createStyles);
  const isMuted = variant === 'muted';

  return (
    <Text style={[styles.label, isMuted && styles.labelMuted]}>
      {label}
      {suffix ? <Text style={[styles.suffix, isMuted && styles.suffixMuted]}>{` ${suffix}`}</Text> : null}
    </Text>
  );
}
