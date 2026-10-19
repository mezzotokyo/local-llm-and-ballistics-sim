# Windows 11 セットアップ手順

native Windows 11（WSL を使わない構成）で本リポジトリを開発するための手順。
想定構成は **Scoop**（`main` バケット）で導入した Python・Git for Windows・`gh`・
（`webapp` を使う場合は）Node.js。
macOS と挙動を合わせるため、コマンド例は `python3` 表記で統一している。

## 1. 必要なソフト

パッケージマネージャーは **Scoop** を使う。Scoop 未導入の場合は、PowerShell で
まず Scoop 本体を入れる（初回のみ）。

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression
```

`Set-ExecutionPolicy` は、スクリプト実行が制限された既定環境（`Restricted`）でも
インストーラを動かせるようにするため。`-Scope CurrentUser` なので管理者権限は不要。
Scoop は既定で `~\scoop` に導入され、`~\scoop\shims` が PATH に追加される。

続けて、目的のツールをまとめて導入する。`git` は Scoop がバケット操作に使うため、
先頭に指定する（後ろに置くといちいち git の導入を求められる）。

```powershell
scoop install git python gh nodejs
```

opencode（開発支援 CLI）は必要に応じて導入する。

```powershell
scoop install opencode
```

| ソフト | 用途 | 備考 |
|--------|------|------|
| Python 3.9 以上 | 本体・テストの実行 | Scoop `main` バケット。3.15 で検証済み。`python` / `python3` で起動できる（`py` は Scoop 構成では解決されない。§2 参照） |
| Node.js 20.19 以上 / 22.12 以上 | `webapp` の開発サーバ・ビルド | Scoop `main` バケット（`nodejs`）。Vite 8 の要件。npm 同梱。`webapp` を使わない場合は不要 |
| Git for Windows | リポジトリ操作・フック実行 | Scoop `main` バケット。フックは POSIX シェルで書かれているが、Git for Windows は `sh` を同梱しているためそのまま動く |
| GitHub CLI (`gh`) | GitHub 認証 | Scoop `main` バケット。初回のみ `gh auth login --hostname github.com --git-protocol https --web` |
| opencode | 開発支援 CLI | Scoop `main` バケット。必要に応じて導入 |

Scoop は導入した実行ファイルを `~\scoop\shims` にシムとして置き、このディレクトリを
PATH に通す。`scoop install` 直後に「コマンドが見つからない」と出る場合は、
**新しい PowerShell を開く**か、次のように現在のシェルへ PATH を反映する:

```powershell
$env:Path += ";$env:USERPROFILE\scoop\shims"
gh --version
```

導入済みの一覧と解決先の確認:

```powershell
scoop list
scoop which gh
```

`gh` は認証時にブラウザが開くため、表示されたコードを
https://github.com/login/device に入力して承認する（Windows ではコードは
クリップボードに入らないので控える）。以降の `git clone` / `git push` は
パスワード入力不要（gh が credential helper として働く）。

認証は **リポジトリを clone する前に**済ませること。private リポジトリを未認証で
`git clone` すると失敗し、空のディレクトリだけが残ることがある。

## 2. Python の確認

PowerShell で次を実行する。

```powershell
python --version
python3 --version
```

Scoop の `python` パッケージは `python.exe` と `python3` シムの両方を用意するため、
`python` / `python3` が同じバージョン（例: `Python 3.15.0`）を返せば準備完了。

`py --version` は **Scoop 構成では `No installed Python found!` になる**。
Scoop 版はレジストリ登録せずに動くため、Microsoft Store 版や python.org 版と違い
`py` ランチャーからは解決されない。本リポジトリの手順は `python3` 表記なので
そのまま進めてよい。

解決先のパスを知りたい場合は次のいずれかを使う。**`where python` は使わない**
（PowerShell の `where` は `Where-Object` のエイリアスであり、何も返さない）。

```powershell
(Get-Command python).Source
scoop which python
```

構成の目安:

- 解決先が `~\scoop\apps\python\current\python.exe` を指す → Scoop 構成（本ドキュメントの前提）
- 解決先が `%LocalAppData%\Microsoft\WindowsApps` を指す → Microsoft Store 版

### 2.1 Node.js の確認（`webapp` を使う場合）

`webapp` を使わない場合は不要。PowerShell で次を実行する。

```powershell
node --version
npm --version
```

**Node.js 20.19 以上 / 22.12 以上**（Vite 8 の要件）であれば準備完了。npm は Node.js に
同梱されている。`node` / `npm` は `~\scoop\shims` のシム経由で解決されるため、§1 の
Scoop PATH が通っていれば追加設定は不要。§1 で設定した実行ポリシー（`RemoteSigned`）は
npm のスクリプト実行にもそのまま適用される。

## 3. リポジトリの取得と検証

**先に §1 の `gh auth login` を済ませること。** 認証前に private リポジトリを
`git clone` すると失敗し、空のディレクトリだけが残る。clone の宛先には既存の
空ディレクトリや別のリポジトリを指定しない（ネストの原因になる。§5 参照）。

```powershell
git clone <リポジトリのURL>
cd <リポジトリ名>
python3 -m unittest discover -s range_calculator -p "test_*.py"
python3 tools/check_text_hygiene.py
python3 range_calculator/range_calc.py
```

期待値:

- テスト: `Ran 200 tests` / `OK`
- 文字混入検査: `0 finding(s)`
- `range_calc.py`: シミュレーション結果が表示される

`python3` が無い環境では `python` に読み替える。

## 4. pre-commit フックの有効化

クローンごとに一度だけ、リポジトリルートで次を実行する。ネイティブ Windows では
`bash` / `sh` を別途導入する必要はなく、PowerShell だけで完結する。

```powershell
git config core.hooksPath .githooks
```

フック本体（`.githooks/pre-commit`）や検査スクリプトはリポジトリに含まれているため、
コピーも実行ビットの設定も不要（Windows は実行ビットを表現しない）。他 OS で使う
`tools/bootstrap.sh` はこれら雛形の配置まで行うが、クローン済みなら上記 1 コマンドで
等価（`docs/setup-machine.md` の手順に相当）。設定を確認する場合:

```powershell
git config core.hooksPath
Test-Path .githooks\pre-commit
```

以降、コミットのたびに文字混入検査が自動実行され、混入文字が 1 件でもあれば
コミットが拒否される。フックを一時的に迂回したい場合のみ
`git commit --no-verify` を使う。

**`core.fileMode` を `true` にしない。** Windows は実行ビットを表現できないため、
`core.fileMode=true` にすると `.githooks/pre-commit`（100755）が常に `M` 表示と
なり、誤ってコミットすると macOS/Linux 側でフックが黙って無効化される。**設定せず
OS 既定値のままにする**（macOS/Linux は `true`・Windows は `false` で、どちらも
このリポジトリにとって正しい）。

## 5. 注意事項

- **`data.csv` を Excel で開いて保存しない。** 保存すると BOM または
  Shift_JIS で書き戻され、読み込み時に既定値へ退避（またはエラー）の原因になる。
  編集はテキストエディタで行い、エンコーディングは UTF-8 のままとする。
- **改行コードは LF で固定されている**（リポジトリルートの `.gitattributes`）。
  `core.autocrlf` の設定に関わらず作業ツリーは LF のまま保たれる。
- **バージョン要件は Python 3.9 以上。** 現在は 3.15 で検証している。
- **`webapp` を使う場合は Node.js 20.19 以上 / 22.12 以上**（Vite 8 の要件）。
  検証は §2.1 を参照。
- Scoop 版ツールは `scoop update`（個別なら `scoop update python` / `scoop update nodejs`）
  で更新する。更新後にテストが落ちた場合は `python --version` でバージョン差分を確認する。
- **リポジトリの中では `git clone` を実行しない。** リポジトリ内に `git clone`
  すると同じリポジトリが `src/` としてネストされる。ネスト側の文字混入リテラルを
  誤検出してコミットがブロックされるため、ネストを作ってしまった場合はその
  ディレクトリを削除する（独自変更がなければ安全）。複製が必要な場合は
  リポジトリの外（例: ローカルドライブ直下）でクローンすること。
- **PowerShell 7（`pwsh`）から `scoop` を実行しない。** PowerShell 7 は自分の
  モジュールパスを `PSModulePath` に前置するため、それを引き継いだ Windows
  PowerShell 5.1 では `Get-FileHash` が解決できず、`scoop install` が
  `URL ... is not valid` で失敗することがある。`scoop` は Windows PowerShell 5.1
  から実行する（`pwsh` を使う場合は `pwsh` の中で `scoop` を実行する）。
- **非対話シェルでの GCM のプロンプト待ちは `bootstrap.sh` が防ぐ。**
  `tools/bootstrap.sh` は clone ごとにリポジトリローカルで
  `credential.guiPrompt=false` / `credential.interactive=false` を設定し、
  自動化（opencode 等）での `git fetch` / `git push` が Git Credential Manager の
  対話待ちでブロックするのを防ぐ。グローバル設定は変更しない。

## 6. 関連文書

- 物理モデル・テスト仕様: `range_calculator/SPEC.md`（第7章に開発環境と検証手順）
- Web アプリの起動（Node.js の要件・PATH を含む）: `webapp/README.md`
- デスクトップ GUI の起動・ビルド（Tkinter。追加の実行時依存なし）: `desktop/README.md`
- Ollama 推論サーバー構築（macOS / Windows）: `docs/setup-ollama-server.md`
- 変更履歴: `range_calculator/HISTORY.md`
