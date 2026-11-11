#!/bin/sh
# リポジトリ雛形の複製と pre-commit フックの有効化
#
# 使い方:
#   tools/bootstrap.sh [ターゲットディレクトリ]
#
# ターゲットは省略時カレントディレクトリ。既存リポジトリ・未初期化の
# 新規ディレクトリどちらでも冪等に動作する。雛形は本スクリプト自身が
# あるリポジトリからコピーされるため、別プロジェクトへの配布にも使える
# （例: bash /どこか/リポジトリ/tools/bootstrap.sh 新しいプロジェクト）。

set -eu

BASEDIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$BASEDIR/.." && pwd)

TARGET=${1:-.}
mkdir -p "$TARGET"
TARGET=$(CDPATH= cd -- "$TARGET" && pwd)

fail() {
    printf 'bootstrap: error: %s\n' "$*" >&2
    exit 1
}

# 同一ファイル（ターゲットが本リポジトリ自身）や内容が既に一致する場合は
# cp を省略する。cp は同一パス指定でエラー終了するため。
put() {
    src=$1
    dst=$2
    if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
        return 0
    fi
    cp "$src" "$dst"
}

command -v git >/dev/null 2>&1 || fail 'git not found'
command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 || command -v py >/dev/null 2>&1 || fail 'Python not found (python3 / python / py)'

SRC_TOOL=$REPO_ROOT/tools/check_text_hygiene.py
SRC_HOOK=$REPO_ROOT/.githooks/pre-commit
SRC_ATTR=$REPO_ROOT/.gitattributes
SRC_IGNORE=$REPO_ROOT/.gitignore

for f in "$SRC_TOOL" "$SRC_HOOK" "$SRC_ATTR" "$SRC_IGNORE"; do
    [ -f "$f" ] || fail "missing template: $f"
done

echo "== bootstrap: $TARGET"

if [ -e "$TARGET/.git" ]; then
    echo "  [ok] already a git repository"
else
    echo "  [*] git init"
    git -C "$TARGET" init
fi

mkdir -p "$TARGET/tools" "$TARGET/.githooks"
put "$SRC_TOOL" "$TARGET/tools/check_text_hygiene.py"
put "$SRC_HOOK" "$TARGET/.githooks/pre-commit"
put "$SRC_ATTR" "$TARGET/.gitattributes"

if [ -f "$TARGET/.gitignore" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        grep -Fxq "$line" "$TARGET/.gitignore" 2>/dev/null || printf '%s\n' "$line" >> "$TARGET/.gitignore"
    done < "$SRC_IGNORE"
else
    cp "$SRC_IGNORE" "$TARGET/.gitignore"
fi

git -C "$TARGET" config core.hooksPath .githooks
git -C "$TARGET" config credential.guiPrompt false
git -C "$TARGET" config credential.interactive false
chmod +x "$TARGET/.githooks/pre-commit"

if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else PY="py -3"; fi

echo "  [*] verify: $PY tools/check_text_hygiene.py"
(cd "$TARGET" && $PY tools/check_text_hygiene.py)

echo "== bootstrap OK: hook active in $TARGET"