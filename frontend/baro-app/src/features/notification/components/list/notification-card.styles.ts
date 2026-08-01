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
    padding: Spacing.md + 2,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 13,
    elevation: 2,
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
  title: {
    fontSize: 14.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
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
