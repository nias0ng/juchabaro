import { Palette } from '@/styles';

import type { NotificationType } from '../api/types';

export const NOTIFICATION_ICON_COLORS: Record<NotificationType, { bg: string; dot: string }> = {
  MOVE_REQUEST: { bg: Palette.peach100, dot: Palette.orange400 },
  MOVE_RESPONSE: { bg: Palette.mint100, dot: Palette.emerald500 },
  REMINDER: { bg: Palette.sky100, dot: Palette.blue500 },
  EV_OVERSTAY: { bg: Palette.lavender100, dot: Palette.violet500 },
  EVENT_RESOLVED: { bg: Palette.mint100, dot: Palette.emerald500 },
};

function pad2(value: number): string {
  return value.toString().padStart(2, '0');
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

// Figma의 "방금 전 / N분 전 / 어제 HH:mm / N일 전" 표기를 그대로 재현한다.
export function formatRelativeTime(iso: string): string {
  const target = new Date(iso);
  const now = new Date();
  const diffMinutes = Math.floor((now.getTime() - target.getTime()) / 60_000);
  const dayDiff = Math.round((startOfDay(now).getTime() - startOfDay(target).getTime()) / 86_400_000);

  if (dayDiff <= 0 || isSameDay(now, target)) {
    if (diffMinutes < 1) return '방금 전';
    if (diffMinutes < 60) return `${diffMinutes}분 전`;
    return `${Math.floor(diffMinutes / 60)}시간 전`;
  }

  if (dayDiff === 1) {
    return `어제 ${pad2(target.getHours())}:${pad2(target.getMinutes())}`;
  }

  return `${dayDiff}일 전`;
}

// dueAt/respondedAt 같은 ISO 시각을 F-02 카드의 "HH:mm" 표기로 바꾼다.
export function formatTimeLabel(iso: string | null): string {
  if (!iso) return '-';
  const date = new Date(iso);
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

// 응답 제출 시 보낸 estimatedMinutes를 F-02 "내 응답" 표시 문구로 바꾼다.
export function formatEstimatedMinutesLabel(estimatedMinutes: number | null): string {
  if (estimatedMinutes === null) return '이동 어려움';
  if (estimatedMinutes < 15) return '바로 이동';
  return `${estimatedMinutes}분 이내 이동`;
}
