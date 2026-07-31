import { useState } from 'react';

import { useAuth } from '@/providers/auth-provider';

// I-02(보기)/I-03(수정)은 피그마에서 같은 "내 정보 수정" 화면의 두 상태라서 하나의 훅으로 관리한다.
export function useProfileEditForm() {
  const { user } = useAuth();
  const [isEditing, setIsEditing] = useState(false);
  const [name, setName] = useState(() => user?.nickname ?? '');
  const [password, setPassword] = useState('');

  const startEditing = () => setIsEditing(true);

  // TODO(profile-api): PATCH /users/me가 아직 없어 실제로는 저장하지 않는다.
  // 화면 로컬 상태만 "보기 모드"로 되돌리고, 방금 입력한 이름은 그대로 화면에 남겨서
  // 최소한 이번 세션 안에서는 수정한 것처럼 보이게 한다.
  const save = () => {
    setIsEditing(false);
    setPassword('');
  };

  return { isEditing, name, setName, password, setPassword, startEditing, save };
}
