import { Text, View } from 'react-native';

import { useTheme } from '@/hooks/use-theme';

import { styles } from './form-error-banner.styles';

type FormErrorBannerProps = {
  message: string;
};

export function FormErrorBanner({ message }: FormErrorBannerProps) {
  const theme = useTheme();

  return (
    <View style={[styles.container, { backgroundColor: theme.dangerSurface }]}>
      <Text style={[styles.icon, { color: theme.danger }]}>⚠️</Text>
      <Text style={[styles.text, { color: theme.danger }]}>{message}</Text>
    </View>
  );
}
