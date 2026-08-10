import { View, type ViewProps, type ViewStyle } from 'react-native';

import { styles } from './stack.styles';

type StackProps = ViewProps & {
  direction?: ViewStyle['flexDirection'];
  gap?: number;
  align?: ViewStyle['alignItems'];
  justify?: ViewStyle['justifyContent'];
  fill?: boolean;
  wrap?: boolean;
};

export function Stack({
  direction = 'column',
  gap = 0,
  align,
  justify,
  fill = false,
  wrap = false,
  style,
  ...props
}: StackProps) {
  return (
    <View
      style={[
        { flexDirection: direction, gap, alignItems: align, justifyContent: justify },
        fill && styles.fill,
        wrap && styles.wrap,
        style,
      ]}
      {...props}
    />
  );
}
