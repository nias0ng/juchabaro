import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  card: {
    width: '100%',
    backgroundColor: Palette.white,
    borderRadius: Radius.input - 2,
    paddingHorizontal: Spacing.base + 3,
    paddingVertical: Spacing.base + 1,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.05,
    shadowRadius: 9,
    elevation: 2,
  },
  cardError: {
    borderWidth: 1,
    borderColor: Palette.orange400,
  },
  plateText: {
    fontSize: 14,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    padding: 0,
  },
  errorText: {
    marginTop: Spacing.xs,
    fontSize: 11.5,
    color: Palette.orange600,
  },
});
