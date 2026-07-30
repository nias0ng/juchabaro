import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    gap: Spacing.md - 2,
    alignItems: 'flex-start',
    width: '100%',
    backgroundColor: Palette.white,
    borderRadius: Radius.xl,
    borderWidth: 1,
    borderColor: 'transparent',
    padding: Spacing.md + 2,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 13,
    elevation: 2,
  },
  containerUnread: {
    borderColor: Palette.lavender100,
  },
  iconOuter: {
    width: 42,
    height: 42,
    borderRadius: 15,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconInner: {
    width: 16,
    height: 16,
    borderRadius: 5,
  },
  content: {
    flex: 1,
    gap: Spacing.xs,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.xs + 3,
  },
  title: {
    fontSize: 14.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  unreadDot: {
    width: 7,
    height: 7,
    borderRadius: 3.5,
    backgroundColor: Palette.coral500,
  },
  body: {
    fontSize: 12.5,
    lineHeight: 20,
    color: Palette.gray500,
  },
  meta: {
    fontSize: 11,
    color: Palette.gray400,
  },
});
