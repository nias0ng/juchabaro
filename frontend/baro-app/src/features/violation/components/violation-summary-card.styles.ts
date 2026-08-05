import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  card: {
    width: '100%',
    borderRadius: 26,
    padding: Spacing.lg - 4,
    gap: Spacing.base + 2,
  },
  label: {
    fontSize: 12.5,
    color: '#4a5568',
  },
  statRow: {
    flexDirection: 'row',
    gap: Spacing.sm + 2,
    justifyContent: 'center',
  },
  statTile: {
    flex: 1,
    backgroundColor: 'rgba(255, 255, 255, 0.85)',
    borderRadius: 18,
    padding: Spacing.base + 2,
    gap: 3,
  },
  statLabel: {
    fontSize: 11,
    color: '#5c6070',
  },
  statValue: {
    fontSize: 22,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  statValueDanger: {
    color: Palette.orange600,
  },
});
