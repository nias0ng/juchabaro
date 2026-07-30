import { StyleSheet } from 'react-native';

import { FontWeight, Palette } from '@/styles';

export const styles = StyleSheet.create({
  card: {
    width: '100%',
    borderRadius: 24,
    padding: 16,
    gap: 11,
    alignItems: 'stretch',
  },
  topRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
  },
  badge: {
    backgroundColor: 'rgba(255,255,255,0.75)',
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingTop: 4,
    paddingBottom: 5,
  },
  badgeText: {
    fontSize: 9.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  statusGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  approvalBadge: {
    backgroundColor: Palette.white,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingTop: 4,
    paddingBottom: 5,
  },
  approvalBadgeText: {
    fontSize: 9.5,
    fontWeight: FontWeight.bold,
    color: Palette.teal600,
  },
  plateGroup: {
    gap: 2,
  },
  plate: {
    fontSize: 22,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    letterSpacing: 0.3,
  },
  subtitle: {
    fontSize: 11,
    color: '#4a5568',
  },
  infoRow: {
    flexDirection: 'row',
    gap: 7,
  },
  infoBox: {
    flex: 1,
    backgroundColor: 'rgba(255,255,255,0.75)',
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 8,
    gap: 1,
  },
  infoLabel: {
    fontSize: 9,
    color: '#5c6070',
  },
  infoValue: {
    fontSize: 11.5,
    fontWeight: FontWeight.semibold,
    color: Palette.gray975,
  },
  deleteButton: {
    height: 36,
    borderRadius: 999,
    backgroundColor: 'rgba(255,255,255,0.85)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  deleteButtonPressed: {
    backgroundColor: 'rgba(255,255,255,0.7)',
  },
  deleteButtonText: {
    fontSize: 11.5,
    fontWeight: FontWeight.bold,
    color: Palette.orange600,
  },
});
