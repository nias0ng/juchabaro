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
  bellShape: {
    width: 15,
    height: 16,
    borderWidth: 1.3,
    borderColor: Palette.gray975,
    borderTopLeftRadius: 6,
    borderTopRightRadius: 6,
    borderBottomLeftRadius: 3,
    borderBottomRightRadius: 3,
  },
  notificationDot: {
    position: 'absolute',
    top: 8,
    right: 9,
    width: 10,
    height: 10,
    borderRadius: Radius.full,
    backgroundColor: Palette.coral500,
    borderWidth: 1,
    borderColor: Palette.white,
  },
});
