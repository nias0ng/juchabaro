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

export type UserStatus = 'PENDING' | 'ACTIVE' | 'REJECTED' | 'SUSPENDED' | 'DELETED';

// GET /api/users/me 응답의 result. 관리자 계정은 buildingNumber/unitNumber가 null이다.
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
