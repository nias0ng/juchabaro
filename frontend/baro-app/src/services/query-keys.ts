import type { MoveRequestScope } from '@/features/move-request/api/types';

export const queryKeys = {
  parking: {
    sessions: () => ['parking', 'sessions'] as const,
    zoneSummary: () => ['parking', 'zoneSummary'] as const,
  },
  violation: {
    stats: () => ['violation', 'stats'] as const,
  },
  moveRequests: {
    all: ['moveRequests'] as const,
    lists: () => [...queryKeys.moveRequests.all, 'list'] as const,
    list: (scope: MoveRequestScope) => [...queryKeys.moveRequests.lists(), scope] as const,
    details: () => [...queryKeys.moveRequests.all, 'detail'] as const,
    detail: (id: number) => [...queryKeys.moveRequests.details(), id] as const,
  },
  vehicles: {
    all: ['vehicles'] as const,
    summary: () => [...queryKeys.vehicles.all, 'summary'] as const,
    management: () => [...queryKeys.vehicles.all, 'management'] as const,
  },
  notifications: {
    list: () => ['notifications', 'list'] as const,
    settings: () => ['notifications', 'settings'] as const,
  },
} as const;
