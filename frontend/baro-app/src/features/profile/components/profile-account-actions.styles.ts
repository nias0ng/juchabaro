import { StyleSheet } from 'react-native';

import { ControlHeight, FontWeight, Palette, Radius, Spacing } from '@/styles';

export const LOGOUT_COLOR = '#ba1a1a';

export const styles = StyleSheet.create({
  logoutButton: {
    alignItems: 'center',
    justifyContent: 'center',
    width: '100%',
    minHeight: ControlHeight.md,
    paddingVertical: Spacing.base + 1,
    borderRadius: Radius.lg,
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
    color: LOGOUT_COLOR,
  },
  withdrawLink: {
    alignItems: 'center',
    paddingTop: Spacing.xs,
    paddingBottom: Spacing.xl,
  },
  withdrawText: {
    fontSize: 12.5,
    fontWeight: FontWeight.medium,
    color: Palette.gray400,
    textDecorationLine: 'underline',
  },
});
