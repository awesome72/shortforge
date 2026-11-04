// 아이폰 기본 사진(HEIC)은 아직 받지 않는다. 파일 선택 창에서 아예 안 보이면 사장님이 왜 못 고르는지 몰라서,
// 고를 수는 있게 두고 고른 순간 JPG로 바꾸는 방법을 알려 준다
export const HEIC_EXT = /\.(heic|heif)$/i;
export const HEIC_ACCEPT = ".heic,.heif";
export const HEIC_HINT =
  "아이폰 사진(HEIC)은 아직 쓸 수 없어요. 아이폰 설정 → 사진 → 'Mac 또는 PC로 전송'을 '자동'으로 두고 " +
  "다시 옮기면 JPG로 바뀌어요. 앞으로 찍을 사진은 설정 → 카메라 → 포맷 → '높은 호환성'으로 JPG가 돼요.";

export const isHeic = (file: File) => HEIC_EXT.test(file.name);
