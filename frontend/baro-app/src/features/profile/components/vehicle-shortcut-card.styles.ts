import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  pressable: {
    width: '100%',
    borderRadius: Radius.lg,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.05,
    shadowRadius: 10,
    elevation: 2,
  },
  pressablePressed: {
    opacity: 0.82,
  },
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.base,
    width: '100%',
    minHeight: 76,
    borderRadius: Radius.lg,
    paddingHorizontal: Spacing.md,
    backgroundColor: Palette.white,
  },
  iconBadge: {
    width: 38,
    height: 38,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: Radius.md,
    backgroundColor: Palette.violet100,
  },
  textGroup: {
    flex: 1,
    gap: 2,
  },
  title: {
    fontSize: 14,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  subtitle: {
    fontSize: 11,
    color: Palette.gray700,
  },
  chevron: {
    fontSize: 19,
    lineHeight: 22,
    color: Palette.gray975,
  },
});
