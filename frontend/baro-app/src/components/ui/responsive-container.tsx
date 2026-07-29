import { useWindowDimensions, View, type ViewProps } from 'react-native';

import { Breakpoints, MaxContentWidth, Spacing } from '@/styles';

import { styles } from './responsive-container.styles';

type ResponsiveContainerProps = ViewProps & {
  maxWidth?: number;
  gutter?: number;
};

export function ResponsiveContainer({
  maxWidth = MaxContentWidth,
  gutter = Spacing.lg,
  style,
  ...props
}: ResponsiveContainerProps) {
  const { width } = useWindowDimensions();
  const horizontalPadding = width < Breakpoints.compact ? Spacing.lg : gutter;

  return (
    <View
      style={[styles.container, { maxWidth, paddingHorizontal: horizontalPadding }, style]}
      {...props}
    />
  );
}
