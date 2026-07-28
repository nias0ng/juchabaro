import {
  ActivityIndicator,
  Pressable,
  Text,
  type PressableProps,
  type PressableStateCallbackType,
} from 'react-native';

import { useTheme } from '@/hooks/use-theme';
import { Palette } from '@/styles';

import { styles } from './app-button.styles';

type AppButtonVariant = 'primary' | 'secondary' | 'neutral';
type AppButtonSize = 'sm' | 'md' | 'lg';

type AppButtonProps = Omit<PressableProps, 'children'> & {
  label: string;
  variant?: AppButtonVariant;
  size?: AppButtonSize;
  fullWidth?: boolean;
  loading?: boolean;
};

export function AppButton({
  label,
  variant = 'primary',
  size = 'md',
  fullWidth = false,
  loading = false,
  disabled = false,
  style,
  ...props
}: AppButtonProps) {
  const theme = useTheme();
  const isDisabled = disabled || loading;

  const variantColors = {
    primary: {
      backgroundColor: theme.primary,
      borderColor: theme.primary,
      textColor: theme.onPrimary,
    },
    secondary: {
      backgroundColor: theme.surface,
      borderColor: theme.primarySoft,
      textColor: theme.primary,
    },
    neutral: {
      backgroundColor: Palette.gray950,
      borderColor: Palette.gray950,
      textColor: Palette.white,
    },
  }[variant];

  const resolveStyle = (state: PressableStateCallbackType) => {
    const customStyle = typeof style === 'function' ? style(state) : style;

    return [
      styles.base,
      styles[size],
      {
        backgroundColor: variantColors.backgroundColor,
        borderColor: variantColors.borderColor,
      },
      fullWidth && styles.fullWidth,
      state.pressed && styles.pressed,
      isDisabled && styles.disabled,
      customStyle,
    ];
  };

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: isDisabled, busy: loading }}
      disabled={isDisabled}
      style={resolveStyle}
      {...props}
    >
      {loading ? (
        <ActivityIndicator color={variantColors.textColor} />
      ) : (
        <Text style={[styles.label, { color: variantColors.textColor }]}>{label}</Text>
      )}
    </Pressable>
  );
}
