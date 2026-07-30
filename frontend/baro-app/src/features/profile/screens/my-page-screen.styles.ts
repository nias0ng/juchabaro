import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  title: {
    fontSize: 24,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    paddingTop: Spacing.xs,
  },
  logoutButton: {
    alignItems: 'center',
    justifyContent: 'center',
    width: '100%',
    paddingVertical: Spacing.base + 1,
    borderRadius: 999,
    backgroundColor: Palette.white,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.05,
    shadowRadius: 9,
    elevation: 1,
  },
  logoutButtonPressed: {
    backgroundColor: Palette.gray50,
  },
  logoutText: {
    fontSize: 14,
    fontWeight: FontWeight.medium,
    color: Palette.red500,
  },
});
