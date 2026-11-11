# サードパーティライセンス / Third-Party Notices

本リポジトリ自体のライセンスは **MIT License**（[`LICENSE`](LICENSE)）です。
本ドキュメントは、本プロジェクトが使用する外部コンポーネントのライセンスと、
実行ファイル・ビルド成果物を配布する際の注意点をまとめたものです。

## 依存コンポーネント

| コンポーネント | ライセンス | 同梱の有無 |
| :--- | :--- | :--- |
| Python（標準ライブラリ・ランタイム） | PSF-2.0 | desktop 実行ファイル（PyInstaller）に同梱 |
| Tcl/Tk（Tkinter の基盤） | BSD 系（Tcl/Tk license） | desktop 実行ファイルに同梱 |
| PyInstaller | GPL-2.0-or-later（例外条項付き） | ビルド時にのみ使用。生成物は GPL 化しません |
| React / React DOM | MIT | webapp のビルド成果物（`dist/`）に同梱 |
| Vite | MIT | ビルド時にのみ使用（成果物にランタイムヘルパを含む場合あり） |
| TypeScript | Apache-2.0 | ビルド時のみ |
| PyInstaller 補助（`pyinstaller-hooks` 等） | 各パッケージに準拠 | ビルド時のみ |
| React / React DOM の型定義（`@types/*`） | MIT | 開発時のみ |
| @vitejs/plugin-react | MIT | ビルド時のみ |
| oxlint | MIT | 開発時のみ |
| Ollama | MIT | 同梱しません（外部サーバーとして利用） |

## 配布時の注意

- 本リポジトリに第三者のバイナリやビルド成果物は含まれていません
  （`webapp/dist/`、`webapp/node_modules/`、`desktop/build/`、`desktop/dist/` は
  バージョン管理の対象外です）。**ソースを公開するだけなら、追加の notice は
  不要です。**
- それらの生成物を配布する場合（GitHub Release への添付など）は、同梱される
  コンポーネントの条項に従い、著作権表示とライセンス全文を配布物へ含めてください。
  ライセンス全文は各パッケージ内（`node_modules/<name>/LICENSE` など）と、
  Python・Tcl/Tk の配布物に付属します。
- **PyInstaller** は「GPL-2.0-or-later（例外条項付き）」です。同条項により、
  生成した実行ファイルが GPL になることはありません。
- `webapp/package.json` の `"private": true` は npm への誤公開を防ぐ指定であり、
  本プロジェクトのライセンスとは無関係です。

## 参考リンク

- Python Software Foundation License: https://docs.python.org/3/license.html
- Tcl/Tk License: https://www.tcl.tk/software/tcltk/license.html
- PyInstaller License: https://pyinstaller.org/en/stable/license.html
- React (MIT): https://github.com/facebook/react/blob/main/LICENSE
- Vite (MIT): https://github.com/vitejs/vite/blob/main/LICENSE
- TypeScript (Apache-2.0): https://github.com/microsoft/TypeScript/blob/main/LICENSE.txt
- Ollama (MIT): https://github.com/ollama/ollama/blob/main/LICENSE
