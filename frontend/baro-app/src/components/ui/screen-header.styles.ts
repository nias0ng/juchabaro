import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    paddingTop: Spacing.lg,
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: Palette.white,
    alignItems: 'center',
    justifyContent: 'center',
  },
  backIcon: {
    width: 9,
    height: 9,
    borderRightWidth: 2,
    borderBottomWidth: 2,
    borderColor: Palette.gray975,
    transform: [{ rotate: '135deg' }],
  },
  title: {
    fontSize: 16,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  right: {
    marginLeft: 'auto',
  },
});
