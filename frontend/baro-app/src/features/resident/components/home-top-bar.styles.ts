import { StyleSheet } from 'react-native';

import { ControlHeight, Palette, Radius, Spacing, Typography } from '@/styles';

export const styles = StyleSheet.create({
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: Spacing.lg,
  },
  unitPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
    backgroundColor: Palette.white72,
    borderRadius: Radius.full,
    paddingVertical: Spacing.sm,
    paddingLeft: Spacing.sm,
    paddingRight: Spacing.md,
  },
  unitText: {
    ...Typography.smallBold,
    color: Palette.gray975,
  },
  notificationButton: {
    width: ControlHeight.sm,
    height: ControlHeight.sm,
    borderRadius: Radius.full,
    backgroundColor: Palette.white80,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
