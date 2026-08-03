export type EventStatus = '진행 중' | '검토 중' | '완료';

export type EventRow = {
  id: string;
  car: string;
  type: string;
  loc: string;
  time: string;
  ai: string;
  st: EventStatus;
  date: string;
};

export type TimelineEntry = {
  t: string;
  d: string;
  time: string;
};

export type HistoryLogEntry = {
  logId: string;
  eventId: string;
  car: string;
  actionType: string;
  handler: string;
  time: string;
  memo: string;
};
