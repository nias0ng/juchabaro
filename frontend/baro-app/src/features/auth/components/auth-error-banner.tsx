import { Text, View } from 'react-native';

import { useTheme } from '@/hooks/use-theme';

import { styles } from './auth-error-banner.styles';

type AuthErrorBannerProps = {
  message: string;
};

export function AuthErrorBanner({ message }: AuthErrorBannerProps) {
  const theme = useTheme();

  return (
    <View style={[styles.container, { backgroundColor: theme.dangerSurface }]}>
      <Text style={[styles.icon, { color: theme.danger }]}>⚠️</Text>
      <Text style={[styles.text, { color: theme.danger }]}>{message}</Text>
    </View>
  );
}
