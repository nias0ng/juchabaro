import { Pressable, Text, View } from 'react-native';

import { ProfileAvatar } from '@/features/profile/components/profile-avatar';

import { styles } from './profile-avatar-editor.styles';

type ProfileAvatarEditorProps = {
  name: string;
};

// 사진 업로드 라이브러리(예: expo-image-picker)가 아직 없어 배지는 장식으로만 두고 탭해도 동작하지 않는다.
export function ProfileAvatarEditor({ name }: ProfileAvatarEditorProps) {
  const initial = name.trim().charAt(0) || '?';

  return (
    <View style={styles.container}>
      <View style={styles.avatarWrap}>
        <ProfileAvatar label={initial} size={82} radius={30} fontSize={28} />
        <View style={styles.cameraBadge} />
      </View>
      <Pressable accessibilityRole="button" disabled>
        <Text style={styles.caption}>프로필 사진 변경</Text>
      </Pressable>
    </View>
  );
}
