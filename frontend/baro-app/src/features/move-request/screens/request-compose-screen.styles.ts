import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    content: {
      flexGrow: 1,
      gap: Spacing.lg,
      paddingBottom: Spacing.xxl,
    },
    footer: {
      marginTop: 'auto',
      gap: Spacing.sm,
    },
    privacyNotice: {
      fontSize: 11,
      color: t.text.weaker,
      textAlign: 'center',
    },
    submitButton: {
      width: '100%',
      height: 56,
      borderRadius: Radius.full,
      backgroundColor: t.fill.inverse.strong,
      alignItems: 'center',
      justifyContent: 'center',
    },
    submitButtonDisabled: {
      opacity: 0.6,
    },
    submitButtonText: {
      fontSize: 15,
      fontWeight: FontWeight.bold,
      color: t.text.inverse,
    },
  });
