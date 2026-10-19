# 環境再構築・新規リポジトリ手順（複数マシン共通）

複数のマシン（macOS / Windows / Linux）で同じツール群を利用し、新規に開発環境を
導入する場合や、新規プロジェクトでも同一の開発環境を再現するための共通手順。

前提: **各リポジトリが git リモート（origin）で管理されている**こと。
iCloud Drive 等のクラウド同期フォルダへの依存はしない（Linux でも同じ手順になる）。

## 1. 必要なソフト

| ソフト | 用途 | 備考 |
|--------|------|------|
| Python 3.9 以上 | 文字混入検査・テスト・物理コアの実行 | macOS: Xcode CLT ／ Windows: Scoop ／ Linux: ディストリのパッケージ |
| Node.js 20.19 以上 / 22.12 以上 | `webapp` の開発サーバ・ビルド | Vite 8 の要件。npm 同梱。`webapp` を使わない場合は不要 |
| Git | リポジトリ操作・フック実行 | フックは POSIX シェル。Windows は Git Bash の `sh` / `bash` で実行 |
| GitHub CLI (`gh`) | GitHub 認証・リポジトリ操作 | 認証は `gh auth login` 1 回。HTTPS の credential helper を gh が引き受ける |
| opencode | 開発支援 CLI | macOS: Homebrew ／ Windows: Scoop ／ Linux: 公式インストーラ。必要に応じて導入 |

各 OS の導入手順:

- **macOS**: `xcode-select --install` で `/usr/bin/python3` と `git` が入る。
  （Homebrew 利用の場合: `brew install python git gh node`、opencode は
  `brew install anomalyco/tap/opencode`）
- **Windows**: `scoop install git python gh nodejs`（Scoop `main` バケット）。
  opencode は必要に応じて `scoop install opencode`。詳細は `docs/setup-windows.md` を参照。
- **Linux (例: Ubuntu)**: `sudo apt install python3 git` ／ `gh` は
  [公式手順](https://cli.github.com/) ／ Node.js は
  [NodeSource](https://github.com/nodesource/distributions) ／ opencode は
  [公式インストーラ](https://opencode.ai/docs/)
  （`curl -fsSL https://opencode.ai/install | bash`）等で導入

### GitHub 認証（初回のみ・マシンごと）

```sh
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git --hostname github.com
```

`gh auth login` で表示されたコードを https://github.com/login/device に入力して承認する
（macOS ではコードがクリップボードに入る）。続けて `gh auth setup-git` を実行すると、
github.com に対する git の credential helper として gh が登録され、トークンは OS の
資格情報ストア（macOS: キーチェーン / Windows: 資格情報マネージャー）に保存される。
以後、`git clone` / `git push` / `git pull` はパスワード・対話入力なしで通る。

- **`gh auth setup-git` を省かない。** Scoop の git は Git Credential Manager を
  システム設定で有効にしているため、未設定だと非対話シェルで `git push` が
  ブラウザ認証待ちでブロックすることがある。gh 側の host 限定ヘルパーを優先させる。
- トークン失効時は `gh auth refresh` で再認証する。必要スコープは `repo`。
- 確認: `gh auth status` が「Logged in」、`git ls-remote origin` が無プロンプトで成功。

## 2. リポジトリの取得とフック有効化

新規に開発環境を導入するマシンでも共通。各リポジトリについて:

```sh
git clone <origin のURL> <ディレクトリ名>
cd <ディレクトリ名>
bash tools/bootstrap.sh .
```

`bash tools/bootstrap.sh .` は POSIX/Windows 共通で、実行ビット無しでも動く
（`sh` や `zsh` から実行しても同じ）。

`tools/bootstrap.sh` は次のことを自動で行う（冪等・何度実行しても安全）:

1. 未初期化なら `git init`
2. `.githooks/pre-commit`・`tools/check_text_hygiene.py`・`.gitattributes` を配置（上書き）
3. `.gitignore` は雛形の行を差し込み（既存の行は保持）
4. `git config core.hooksPath .githooks`
5. `credential.guiPrompt=false`・`credential.interactive=false` をリポジトリローカルに設定
   （非対話シェルで opencode 等から `git fetch` / `git push` が GCM の対話待ちで
   ブロックするのを防止。グローバル設定は変更しない）
6. `chmod +x .githooks/pre-commit`
7. 文字混入検査を実行して正常動作を確認

このスクリプトは自分自身が入っているリポジトリを雛形元にするため、
別プロジェクトにも配布できる（例: `bash /path/to/repo/tools/bootstrap.sh 新しいプロジェクト`）。

## 3. 検証

```sh
python3 tools/check_text_hygiene.py
bash tools/bootstrap.sh .
```

期待値は `scanned N file(s), 0 finding(s)`（N はスキャン対象のファイル数）で、
`bootstrap.sh` は 2 回目以降も成功する（冪等チェック）。

任意でフック発火確認: ハングルを 1 文字混入させたファイルを一時的に追加して
`git commit` が拒否されることを確認し、元に戻す。

## 4. 新規リポジトリの作成

1. ホスト（GitHub / GitLab / Gitea 等）で空リポジトリを作成
   （GitHub なら `gh repo create <名前> --private`）
2. `git clone <new-origin> myproj && cd myproj`
3. 雛形を配布: `bash <既存ツールのあるリポジトリ>/tools/bootstrap.sh .`
4. 初期ファイルをコミットして `git push -u origin <ブランチ名>`

複数のリポジトリを管理する場合は、各リポジトリで 2–4 を繰り返す。

## 5. 既存リポジトリに origin を張る

他人からもらったリポジトリなど、origin 未設定の場合は:

```sh
git remote add origin <origin のURL>
git push -u origin <ブランチ名>
```

`<ブランチ名>` は `main` / `v5` などの実際のブランチ名に置き換える。

## 6. クロス機共通の注意

- **リポジトリの内部で `git clone` を実行しない。**
  ネストされたリポジトリが誤検出の原因になり、コミットがブロックされる。
- **`core.fileMode` は設定しない（各 OS の既定値のまま）。**
  macOS/Linux は `true`・Windows は `false` が正しい。特に Windows で
  `core.fileMode=true` にすると `.githooks/pre-commit` が常に `M` 表示になり、
  誤コミットで macOS/Linux のフックが黙って無効化される。
- **モードのみの変更（実行ビット）はコミットしない。**
  フックの `100755` はリポジトリで維持する。`M` が出るときは
  `chmod +x .githooks/pre-commit` で解消する（コミットは不要）。
- フックもリポジトリの一部として origin を介して配布されるため、
  各機での設定は clone 後の `bootstrap.sh` 実行のみで完結する。
- **他機の更新が `git status` に出ないときは `git fetch` を実行する。**
  `git status` の「up to date」はローカルにキャッシュされたリモート追跡参照
  （`origin/<ブランチ>`）との比較であり、fetch するまでは実際の最新とは限らない。
  最新の取り込みは `git pull --ff-only` で行う。VS Code を使う場合は設定
  **`Git: Autofetch`** を有効にすると自動で参照が更新され、この食い違いを防げる
  （既定は無効。小規模リポジトリでは有効化を推奨）。

## 7. 関連文書

- Windows 固有のセットアップ: `docs/setup-windows.md`
- Ollama 推論サーバー構築（macOS / Windows）: `docs/setup-ollama-server.md`
- 文字混入検査の仕様・ルール: `tools/check_text_hygiene.py` の docstring と `--list-rules`