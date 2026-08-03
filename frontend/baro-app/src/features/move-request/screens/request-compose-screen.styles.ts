import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  content: {
    flexGrow: 1,
    gap: Spacing.lg,
    paddingHorizontal: Spacing.lg,
    paddingBottom: Spacing.xxl,
  },
  footer: {
    marginTop: 'auto',
    gap: Spacing.sm,
  },
  privacyNotice: {
    fontSize: 11,
    color: '#9599a7',
    textAlign: 'center',
  },
  submitButton: {
    width: '100%',
    height: 56,
    borderRadius: Radius.full,
    backgroundColor: Palette.gray975,
    alignItems: 'center',
    justifyContent: 'center',
  },
  submitButtonDisabled: {
    opacity: 0.6,
  },
  submitButtonText: {
    fontSize: 15,
    fontWeight: FontWeight.bold,
    color: Palette.white,
  },
});
