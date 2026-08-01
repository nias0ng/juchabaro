import { Redirect } from 'expo-router';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { useAuth } from '@/providers/auth-provider';
import { Palette } from '@/styles';

export default function IndexScreen() {
  const { status, user } = useAuth();

  if (status === 'loading') {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator color={Palette.violet600} />
      </View>
    );
  }

  const isResident = status === 'authenticated' && user?.role === 'RESIDENT';

  return <Redirect href={isResident ? '/resident' : '/auth'} />;
}

const styles = StyleSheet.create({
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.white,
  },
});
