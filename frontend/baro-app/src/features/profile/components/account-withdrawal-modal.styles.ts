import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(20, 22, 28, 0.5)',
    padding: Spacing.lg,
  },
  sheet: {
    width: '100%',
    maxWidth: 360,
    gap: Spacing.base,
    borderRadius: Radius.xl,
    backgroundColor: Palette.white,
    padding: Spacing.lg,
    alignItems: 'center',
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 16 },
    shadowOpacity: 0.18,
    shadowRadius: 20,
    elevation: 6,
  },
  iconCircle: {
    width: 48,
    height: 48,
    borderRadius: Radius.lg,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.orange50,
  },
  iconText: {
    fontSize: 22,
    fontWeight: FontWeight.bold,
    color: Palette.red500,
  },
  title: {
    fontSize: 17,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    textAlign: 'center',
  },
  description: {
    fontSize: 12,
    lineHeight: 19,
    color: Palette.gray500,
    textAlign: 'center',
  },
  notice: {
    width: '100%',
    borderRadius: Radius.md,
    backgroundColor: Palette.orange50,
    paddingHorizontal: Spacing.base,
    paddingVertical: Spacing.sm,
  },
  noticeText: {
    fontSize: 11.5,
    lineHeight: 18,
    color: Palette.orange600,
    textAlign: 'center',
  },
  actions: {
    width: '100%',
    gap: Spacing.sm,
  },
  withdrawButton: {
    minHeight: 46,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: Radius.lg,
    backgroundColor: Palette.red500,
  },
  withdrawButtonPressed: {
    opacity: 0.86,
  },
  withdrawButtonText: {
    fontSize: 13.5,
    fontWeight: FontWeight.bold,
    color: Palette.white,
  },
  cancelButton: {
    minHeight: 42,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: Radius.lg,
    backgroundColor: Palette.gray100,
  },
  cancelButtonPressed: {
    backgroundColor: Palette.gray200,
  },
  cancelButtonText: {
    fontSize: 13,
    fontWeight: FontWeight.medium,
    color: Palette.gray600,
  },
  buttonDisabled: {
    opacity: 0.4,
  },
});
