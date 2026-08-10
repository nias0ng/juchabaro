import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    gap: Spacing.sm,
    marginTop: -Spacing.sm,
    marginBottom: Spacing.sm,
  },
  scroll: {
    marginRight: -Spacing.lg,
  },
  row: {
    flexDirection: 'row',
    gap: Spacing.sm,
    paddingVertical: Spacing.sm,
    paddingLeft: Spacing.xs,
    paddingRight: Spacing.lg + Spacing.xs,
  },
  action: {
    width: 96,
    minHeight: 116,
    justifyContent: 'space-between',
    borderRadius: Radius.input,
    padding: Spacing.base,
    paddingLeft: Spacing.md,
    paddingRight: Spacing.sm,
    gap: Spacing.sm,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.09,
    shadowRadius: 10,
    elevation: 3,
  },
  label: {
    flexShrink: 1,
    fontSize: 18,
    lineHeight: 23,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  chevronBox: {
    position: 'absolute',
    right: Spacing.sm,
    bottom: Spacing.lg - Spacing.xs,
    width: 26,
    height: 26,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: Radius.sm,
  },
  progressTrack: {
    width: 96,
    height: 3,
    alignSelf: 'center',
    overflow: 'hidden',
    borderRadius: Radius.full,
    backgroundColor: Palette.gray200,
  },
  progressThumb: {
    height: '100%',
    borderRadius: Radius.full,
    backgroundColor: Palette.violet500,
  },
});
