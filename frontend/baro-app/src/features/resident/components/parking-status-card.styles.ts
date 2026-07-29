import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    gap: Spacing.sm,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  title: {
    fontSize: 15,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  congestionPill: {
    alignSelf: 'flex-start',
    backgroundColor: Palette.amber50,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm + 1,
    paddingVertical: 3,
  },
  congestionText: {
    fontSize: 10.5,
    fontWeight: FontWeight.bold,
    color: Palette.amber500,
  },
  viewAllText: {
    marginLeft: 'auto',
    fontSize: 12.5,
    color: Palette.violet500,
  },

  card: {
    width: '100%',
    backgroundColor: Palette.white,
    borderRadius: Radius.xxl + 2,
    padding: Spacing.md + 1,
    gap: Spacing.base,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 13,
    elevation: 2,
  },

  mapPreview: {
    width: '100%',
    height: 112,
    borderRadius: Radius.md + 6,
    backgroundColor: '#f5f4fb',
    padding: Spacing.sm,
    gap: Spacing.xs,
  },
  mapRow: {
    flexDirection: 'row',
    gap: Spacing.xs,
  },
  mapCell: {
    flex: 1,
    height: 19,
    borderRadius: 7,
    backgroundColor: '#e7e5f3',
    alignItems: 'center',
    justifyContent: 'center',
  },
  mapCellAlt: {
    backgroundColor: '#d9d5ee',
  },
  mapCellViolation: {
    backgroundColor: Palette.peach100,
  },
  mapCellMine: {
    backgroundColor: Palette.mint100,
  },
  mapCellLabel: {
    fontSize: 9,
    fontWeight: FontWeight.bold,
  },
  legendRow: {
    flexDirection: 'row',
    gap: Spacing.md,
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.xs,
  },
  legendDot: {
    width: 8,
    height: 8,
    borderRadius: 3,
  },
  legendText: {
    fontSize: 10.5,
    color: Palette.gray500,
  },
});
