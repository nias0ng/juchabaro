import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.md,
  },
  iconShadow: {
    width: 80,
    height: 80,
    borderRadius: 40,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 14 },
    shadowOpacity: 0.09,
    shadowRadius: 17,
    elevation: 4,
  },
  iconCircle: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: Palette.white,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  carIcon: {
    width: 128,
    height: 128,
  },
  title: {
    fontSize: 15,
    fontWeight: FontWeight.semibold,
    color: Palette.gray975,
  },
  description: {
    fontSize: 12,
    color: Palette.gray500,
  },
});
