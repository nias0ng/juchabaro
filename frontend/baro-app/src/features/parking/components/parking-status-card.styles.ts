import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Shadows, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    gap: Spacing.xs,
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
  card: {
    width: '100%',
    backgroundColor: Palette.gray25,
    borderRadius: Radius.xxl + 2,
    padding: Spacing.md + 1,
    gap: Spacing.base,
    ...Shadows.card,
  },
  cardHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  floorTabs: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: Spacing.xxs,
    borderRadius: Radius.full,
    backgroundColor: Palette.gray100,
  },
  floorTab: {
    minWidth: 30,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: Spacing.xs,
    paddingVertical: Spacing.xxs,
    borderRadius: Radius.full,
  },
  floorTabActive: {
    backgroundColor: Palette.white,
  },
  floorTabText: {
    fontSize: 11,
    fontWeight: FontWeight.bold,
    color: Palette.gray500,
  },
  floorTabTextActive: {
    color: Palette.violet600,
  },
  carouselFrame: {
    width: '100%',
  },
  floorScroll: {
    width: '100%',
  },
  floorPage: {
    gap: Spacing.sm,
  },
  cardSummaryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.xs,
    paddingRight: Spacing.sm,
  },
});
