#!/bin/sh
# 公開リポジトリへ「最新版のみ」をスナップショット公開する（履歴は残さない）
#
# 使い方:
#   tools/publish.sh [リモート名] [参照]
#   既定: tools/publish.sh public main
#
# 指定した参照（既定 main）のツリーを、親を持たない単一コミットとして
# 公開リポジトリの main へ force-push する。これにより公開側には最新版の
# 内容だけが残り、開発履歴は公開されない。
#
# 注意:
#   - 未コミットの変更は含まれない（必ずコミット済みの参照を指定する）。
#   - force-push のため公開側の既存履歴は到達不能になる。
#   - 内容が同一で公開側が既に単一コミットなら何もしない（冪等）。

set -eu

REMOTE=${1:-public}
REF=${2:-main}
BRANCH=main

BASEDIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$BASEDIR/.." && pwd)
cd "$REPO_ROOT"

fail() {
    printf 'publish: error: %s\n' "$*" >&2
    exit 1
}

git remote get-url "$REMOTE" >/dev/null 2>&1 || fail "リモート '$REMOTE' が見つかりません"
git rev-parse --verify --quiet "$REF^{commit}" >/dev/null || fail "参照 '$REF' が見つかりません"

TREE=$(git rev-parse "$REF^{tree}")
SRC=$(git rev-parse --short "$REF")
REMOTE_REF="refs/remotes/$REMOTE/$BRANCH"

git fetch --quiet "$REMOTE" 2>/dev/null || true

if git rev-parse --verify --quiet "$REMOTE_REF" >/dev/null; then
    REMOTE_TREE=$(git rev-parse "$REMOTE_REF^{tree}")
    COUNT=$(git rev-list --count "$REMOTE_REF")
    if [ "$TREE" = "$REMOTE_TREE" ] && [ "$COUNT" -eq 1 ]; then
        echo "publish: 公開内容は最新です（変更なし）"
        exit 0
    fi
fi

MSG="公開: $SRC ($(date +%Y-%m-%d))"
COMMIT=$(git commit-tree "$TREE" -m "$MSG")

echo "publish: $REMOTE/$BRANCH を $SRC のツリー（単一コミット）で置き換えます"
git push "$REMOTE" "$COMMIT:refs/heads/$BRANCH" --force
echo "publish: 完了"
