type RefreshListener = () => void;

const listeners = new Set<RefreshListener>();

/** 현재 보이는 인증 조회 화면을 기존 데이터 유지 상태로 다시 조회하게 한다. */
export function refreshAuthenticatedQueries(): void {
  listeners.forEach((listener) => listener());
}

export function subscribeAuthenticatedQueryRefresh(listener: RefreshListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
