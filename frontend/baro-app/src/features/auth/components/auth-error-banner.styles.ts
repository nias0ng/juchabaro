import { StyleSheet } from 'react-native';

import { Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: Spacing.sm,
    borderRadius: Radius.lg,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.base,
  },
  icon: {
    fontSize: 12,
  },
  text: {
    flex: 1,
    fontSize: 12,
  },
});
