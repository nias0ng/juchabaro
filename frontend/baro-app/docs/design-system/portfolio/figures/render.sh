#!/usr/bin/env bash
# figures/src/*.html을 PNG로 만든다 (2배 해상도). Windows Chrome 경로 고정.
# 사용법: bash render.sh [이름...]   이름을 생략하면 전부
set -euo pipefail
cd "$(dirname "$0")"
CHROME="${CHROME:-C:/Program Files/Google/Chrome/Application/chrome.exe}"
SRC="$(pwd -W 2>/dev/null || pwd)/src"
OUT="$(pwd -W 2>/dev/null || pwd)"

# 이름 → 창 크기(CSS px). 그림 크기를 바꾸면 여기도 맞춘다.
declare -A SIZE=(
  [dark-mode-before-after]=1144,1460
  [annotated-components]=1072,720
  [naming-rule]=1000,500
  [contrast-before-after]=1000,690
  [structure]=1000,400
  [light-dark-pair]=1144,690
)

NAMES=("$@")
[ ${#NAMES[@]} -eq 0 ] && NAMES=("${!SIZE[@]}")

for NAME in "${NAMES[@]}"; do
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
    --user-data-dir="${TEMP:-/tmp}/figure-render" --window-size="${SIZE[$NAME]}" \
    --virtual-time-budget=3000 --screenshot="$OUT/$NAME.png" "file:///$SRC/$NAME.html" >/dev/null 2>&1
  echo "$NAME.png"
done
