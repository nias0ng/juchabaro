/**
 * 브라우저에는 expo-secure-store 같은 OS 암호화 저장소가 없다.
 * localStorage는 XSS 노출 범위가 넓어 토큰 저장에 쓰지 않고, 탭을 닫으면 사라지는
 * sessionStorage를 사용한다 (admin-web/AGENTS.md "저장소 사용 구분" 참고).
 */
const ACCESS_TOKEN_KEY = 'auth.accessToken';
const REFRESH_TOKEN_KEY = 'auth.refreshToken';

export type Session = {
  accessToken: string;
  refreshToken: string;
};

export function saveSession(session: Session): void {
  sessionStorage.setItem(ACCESS_TOKEN_KEY, session.accessToken);
  sessionStorage.setItem(REFRESH_TOKEN_KEY, session.refreshToken);
}

export function getSession(): Session | null {
  const accessToken = sessionStorage.getItem(ACCESS_TOKEN_KEY);
  const refreshToken = sessionStorage.getItem(REFRESH_TOKEN_KEY);

  // 둘 중 하나라도 없으면 세션이 없는 것으로 취급
  if (!accessToken || !refreshToken) return null;
  return { accessToken, refreshToken };
}

export function clearSession(): void {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  sessionStorage.removeItem(REFRESH_TOKEN_KEY);
}
