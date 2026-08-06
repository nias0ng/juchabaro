import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  content: {
    flexGrow: 1,
    width: '100%',
    alignItems: 'center',
    paddingTop: Spacing.xl + 8,
    paddingBottom: Spacing.lg,
    gap: Spacing.md,
  },
  statusContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: Spacing.xxl,
  },
  statusText: {
    fontSize: 13.5,
    color: Palette.gray500,
    textAlign: 'center',
  },
  iconOuter: {
    width: 88,
    height: 88,
    borderRadius: 44,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.white,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.08,
    shadowRadius: 15,
    elevation: 4,
  },
  iconInner: {
    width: 34,
    height: 34,
    borderRadius: 17,
  },
  title: {
    fontSize: 25,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    textAlign: 'center',
  },
  subtitle: {
    fontSize: 13.5,
    lineHeight: 23.63,
    color: Palette.gray500,
    textAlign: 'center',
  },
  summaryMargin: {
    width: '100%',
    alignItems: 'center',
  },
  noticeBox: {
    width: '100%',
    maxWidth: 346,
    backgroundColor: Palette.white72,
    borderRadius: Radius.xl - 4,
    paddingHorizontal: Spacing.md + 2,
    paddingVertical: Spacing.md,
  },
  noticeText: {
    fontSize: 12,
    lineHeight: 21,
    color: Palette.gray600,
    textAlign: 'center',
  },
  countdownMargin: {
    width: '100%',
    marginTop: 'auto',
  },
});
