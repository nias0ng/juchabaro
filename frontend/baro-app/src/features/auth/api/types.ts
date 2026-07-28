// 노션 API 명세의 필드명을 그대로 옮긴 타입들이다. 백엔드가 필드명을 바꾸면 여기부터 고치면 된다.

export type LoginRequest = {
  loginId: string;
  password: string;
};

export type UserRole = 'RESIDENT' | 'ADMIN';

// 명세의 result 객체 하나. httpStatus/isSuccess/message/code 같은 껍데기는
// http-client가 이미 벗겨내고 이 부분만 돌려주기 때문에 여기엔 없다.
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
  nickname: string;
  role: UserRole;
  status: UserStatus;
  createdAt: string;
};
