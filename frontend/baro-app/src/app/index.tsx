import { Redirect } from 'expo-router';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { useAuth } from '@/providers/auth-provider';
import { Palette } from '@/styles';

export default function IndexScreen() {
  const { status } = useAuth();

  if (status === 'loading') {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator color={Palette.violet600} />
      </View>
    );
  }

  return <Redirect href={status === 'authenticated' ? '/resident' : '/auth'} />;
}

const styles = StyleSheet.create({
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.white,
  },
});
