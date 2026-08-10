import { Text, type TextProps } from 'react-native';

import { useTheme } from '@/hooks/use-theme';
import { type ThemeColor, Typography } from '@/styles';

export type ThemedTextProps = TextProps & {
  type?: 'default' | 'title' | 'small' | 'smallBold' | 'subtitle' | 'link' | 'linkPrimary' | 'code';
  themeColor?: ThemeColor;
};

export function ThemedText({ style, type = 'default', themeColor, ...rest }: ThemedTextProps) {
  const theme = useTheme();

  return (
    <Text
      style={[
        { color: theme[themeColor ?? 'text'] },
        type === 'default' && Typography.body,
        type === 'title' && Typography.title,
        type === 'small' && Typography.small,
        type === 'smallBold' && Typography.smallBold,
        type === 'subtitle' && Typography.subtitle,
        type === 'link' && Typography.link,
        type === 'linkPrimary' && [Typography.link, { color: theme.primary }],
        type === 'code' && Typography.code,
        style,
      ]}
      {...rest}
    />
  );
}
