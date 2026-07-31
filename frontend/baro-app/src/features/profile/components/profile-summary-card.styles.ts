import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.md,
    width: '100%',
    borderRadius: 28,
    backgroundColor: Palette.white,
    padding: Spacing.lg - 2,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.07,
    shadowRadius: 15,
    elevation: 3,
  },
  info: {
    flex: 1,
    gap: 3,
  },
  name: {
    fontSize: 19,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  meta: {
    fontSize: 12.5,
    color: Palette.gray500,
  },
  statusBadge: {
    backgroundColor: Palette.teal100,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm + 4,
    paddingVertical: Spacing.xs + 2,
  },
  statusText: {
    fontSize: 11,
    fontWeight: FontWeight.bold,
    color: Palette.teal600,
  },
});
