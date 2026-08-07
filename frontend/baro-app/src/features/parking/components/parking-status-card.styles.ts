import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Shadows, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    gap: Spacing.sm,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  title: {
    fontSize: 15,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  congestionPill: {
    alignSelf: 'flex-end',
    marginRight: Spacing.lg - (Spacing.md + 1),
  },
  card: {
    width: '100%',
    backgroundColor: Palette.white80,
    borderRadius: Radius.xxl + 2,
    padding: Spacing.md + 1,
    gap: Spacing.base,
    ...Shadows.card,
  },
});
