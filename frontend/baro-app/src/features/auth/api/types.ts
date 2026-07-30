// POST /api/auth/login 요청 body.
export type LoginRequest = {
  loginId: string;
  password: string;
};

export type UserRole = 'RESIDENT' | 'ADMIN';

// POST /api/auth/login 응답의 result.
export type LoginResult = {
  accessToken: string;
  refreshToken: string;
  tokenType: string;
  expiresIn: number;
  userId: number;
  nickname: string;
  role: UserRole;
};

export type UserStatus = 'ACTIVE' | 'DELETED' | 'SUSPENDED';

// GET /api/users/me 응답의 result. buildingNumber/unitNumber는 관리자 계정이면 null일 수 있다.
export type UserProfile = {
  userId: number;
  loginId: string;
  phoneNumber: string;
  buildingNumber: string | null;
  unitNumber: string | null;
  name: string;
  role: UserRole;
  status: UserStatus;
  createdAt: string;
};

// POST /api/auth/signup 요청 body.
export type SignupRequest = {
  loginId: string;
  password: string;
  phoneNumber: string;
  name: string;
  buildingNumber: string;
  unitNumber: string;
};

// POST /api/auth/signup 응답의 result. 토큰은 내려오지 않는다 (가입 후 자동 로그인 없음).
export type SignupResult = {
  userId: number;
  phoneNumber: string;
  name: string;
  role: UserRole;
  status: UserStatus;
};
