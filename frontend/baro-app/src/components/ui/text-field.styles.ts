import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    width: '100%',
    gap: Spacing.sm,
  },
  label: {
    fontSize: 12.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray600,
  },
  field: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: Spacing.sm,
    width: '100%',
    borderRadius: Radius.input,
    backgroundColor: Palette.white,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.md,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.05,
    shadowRadius: 9,
    elevation: 1,
  },
  fieldError: {
    borderWidth: 1,
  },
  input: {
    flex: 1,
    fontSize: 14,
    color: Palette.gray975,
    padding: 0,
  },
  errorText: {
    fontSize: 11,
  },
});
