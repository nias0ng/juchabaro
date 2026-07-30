import { Image } from 'expo-image';

const mainIcon = require('@/assets/images/main-icon.png');

type MainIconProps = {
  size?: number;
};

/** Figma Z-01. MainIcon(node 2023:2)을 그대로 재현한 앱 로고. 둥근 모서리와 그림자는 이미지 자체에 포함되어 있다. */
export function MainIcon({ size = 96 }: MainIconProps) {
  return <Image source={mainIcon} style={{ width: size, height: size }} contentFit="contain" />;
}
