# Range Calculator Desktop (desktop)

`range_calculator` の弾道シミュレーションを、ブラウザを使わずにネイティブ GUI で
操作・可視化するデスクトップアプリです。GUI は Python 標準ライブラリの Tkinter
（ttk）で構築し、物理計算は既存の `range_calculator`（`ballistics` /
`physics_config`）をそのまま再利用します。

対応 OS は **Windows 11（主）** と **macOS（副）** です。実行時依存は Python 標準
ライブラリのみで、追加の `pip` パッケージは不要です（ビルド時のみ PyInstaller を
使います。§4）。

機能は `webapp` と同等です（入力・Result メトリクス・軌跡チャート）。GUI は用途別に
**2 つの独立したウィンドウ**へ分かれています。

- **弾道（`ballistic_app.py`）**: 地表弾道。初速・発射角・抗力の密度モデルと、回転
  （Magnus 揚力。スピン回転数・スピン軸角）を指定できる。軌跡は断面（x–y）と上面
  （x–z）を切り替え可能。
- **軌道**（`orbital_app.py`）: 中心重力（ニュートン / ニュートン+J2）。軌道半径と
  軌道速度（既定は円軌道速度を自動設定）を指定する。

共通のヘルパーは `app_common.py` に集約しています。対応関係と設計の詳細は
`desktop/PLAN.md` を参照してください。

---

## 1. 前提環境

- **Python 3.9 以上**（Windows: `python` / `python3`、macOS: `python3`）
- Tkinter（Python 同梱。Scoop の Python 3.15 / python.org 版で動作確認）
  - Tk のバージョン確認: `python3 -c "import tkinter; print(tkinter.TkVersion)"`

追加の `pip` パッケージは不要です。

---

## 2. 起動方法

リポジトリのルートで実行します。

Windows:

```powershell
python desktop/ballistic_app.py
python desktop/orbital_app.py
```

macOS:

```sh
python3 desktop/ballistic_app.py
python3 desktop/orbital_app.py
```

起動時に既定値（初速 170 km/h、発射角 35 deg、Cd 0.47、刻み幅 dt は弾道 0.01 s・軌道 1 s
など）で 1 回自動実行されます。

---

## 3. 操作方法

### 3.1 弾道ウィンドウ（`ballistic_app.py`）

1. **発射速度** と **発射角** のスライダーを動かす。
2. **抗力係数 Cd** は既定プロファイルの球体代表値 **0.47 に固定**（UI では読み取り専用の
   ラベル。プルダウンによる球種選択は廃止）。
3. **抗力（密度）モデル** を選ぶ（なし / 一様 / 指数 / 区分指数）。「なし」は抗力を
   無効化（`Cd=0`）する。
4. **スピン（Magnus 揚力）** の **回転数**（0–6000 rpm）と **スピン軸角**（-180–180 deg）
   を設定する。軸角 0 はバックスピン、+90 は *+z*、−90 は *−z*、±180 はトップスピン。
   回転数 0 で Magnus 効果は無効。
5. 必要に応じて **刻み幅 dt**（0.0001–10、0.0001 単位）を変更し、**adaptive** を
   有効にする。
6. **表示** を「断面 (x–y)」または「上面 (x–z)」（スピンによる左右のずれ）から選ぶ。
7. 「**シミュレーション実行**」を押す。計算中は `計算中...` を表示し、完了すると
   **Result** にメトリクス、下段 **Trajectory** に軌跡チャートが表示される。
8. エラー時は Result を更新せず、日本語のエラーメッセージを表示する。

### 3.2 軌道ウィンドウ（`orbital_app.py`）

1. **重力モデル** をプルダウンで選ぶ（**ニュートン（軌道）** / **ニュートン+J2（軌道）**。
   地表弾道の「一定」は含まない）。J2 は地球扁平の摂動を加える。
2. **軌道半径 r** のスライダーを動かす。**軌道速度 v** は「円軌道速度を自動設定」で
   `sqrt(mu/r)` に追従し、オフにすると手動指定できる。
   閉軌道では **1 周期分**（周期 × 1.05）を自動積分するため、軌道が一周して閉じる。
   このとき刻み幅は周期 / 4000 を上限に自動調整され（`dt` をそれより細かく指定しても
   上限に丸められる）、着弾前提の時間上限警告は表示しない。
3. **抗力係数 Cd** は弾道ウィンドウと同じく **0.47 に固定**。
4. **抗力（密度）モデル** を選ぶ（なし / 一様 / 指数 / 区分指数）。「なし」は抗力を
   無効化（`Cd=0`）する。**軌道計算では「なし」を推奨**する（抗力下では安定刻みが
   極端に小さくなり、発散しやすくなる）。
5. 必要に応じて **刻み幅 dt** と **adaptive** を変更する。
6. 「**シミュレーション実行**」を押すと **Result** に軌道要素（長半径・離心率など）、
   下段 **Trajectory** に軌跡チャートが表示される。
7. エラー時は Result を更新せず、日本語のエラーメッセージを表示する。

`adaptive` は刻みを安定性上限内に短縮する発散防止機構であり、精度向上を保証する
ものではありません（詳細は `range_calculator/SPEC.md` 第4章）。

---

## 4. 実行ファイルのビルド（任意）

配布用の自己完結ファイルを作る場合は PyInstaller を使います。**ビルド時のみ**
必要で、アプリの実行には不要です。

```sh
pip install pyinstaller
python3 desktop/build.py
```

- Windows: `desktop/dist/range_calculator_ballistic.exe`,
  `desktop/dist/range_calculator_orbital.exe`
- macOS: `desktop/dist/range_calculator_ballistic`, `desktop/dist/range_calculator_orbital`
  （必要なら `.app` 化）

`build.py` は 2 つの実行ファイルを生成します（弾道・軌道で 1 つずつ）。物理定数の
設定ファイル（`range_calculator/config/physics_constants.json`）を両方に同梱します。
ビルド後、実行ファイルを起動して物理定数の `physics config not found` 警告が出ない
ことを確認してください。

---

## 5. テスト

リポジトリのルートで実行します。

```sh
python3 -m unittest discover -s desktop/tests -p "test_*.py"
python3 -m unittest discover -s range_calculator -p "test_*.py"
python3 tools/check_text_hygiene.py
```

`desktop/tests/test_agreement.py` は、`webapp` と意図的に重複させている
エラー変換・抗力係数プリセット（既定の球体 `Cd=0.47`）・simulate グルーが食い違って
いないかを検査します。
`webapp` 側を変更したら、`desktop` 側も追随させてください（詳細は
`desktop/PLAN.md` §9）。

---

## 6. 構成

```text
desktop/
  app_common.py          # 共有 GUI 基盤（queue / スレッド / メトリクス描画 / スライダー）
  ballistic_app.py       # 弾道ウィンドウ（エントリポイント）
  orbital_app.py         # 軌道ウィンドウ（エントリポイント）
  gui_model.py           # GUI 非依存の純ロジック（プリセット・検証・simulate）
  trajectory_chart.py    # Canvas 製の軌跡チャート（断面 x–y / 上面 x–z）
  errors.py              # 英語例外→日本語
  build.py               # PyInstaller によるビルド（2 実行ファイル）
  PLAN.md                # 開発計画書
  tests/
    test_gui_model.py       # 純ロジックの単体テスト
    test_trajectory_chart.py # チャートのスケーリング計算の単体テスト
    test_agreement.py       # webapp との対応漏れ検出
```

---

## 7. トラブルシューティング

| 症状 | 原因 / 対処 |
|------|-------------|
| `ModuleNotFoundError: tkinter` | Python に Tk が含まれていない。python.org 版または Scoop の Python を使う |
| 起動しても何も表示されない | 追加の `pip` 依存は不要。`python3 desktop/ballistic_app.py`（または `orbital_app.py`）をフォアグラウンドで実行しエラーを確認する |
| `physics config not found` 警告 | 設定ファイルが見つからず組み込み既定値で動作。ビルド版では `build.py` の同梱設定を確認する |
| 計算が長い | `dt` を大きくするか `adaptive` を有効にする。`dt=0.0001`・時間上限 300 s では最大 300 万ステップになり得る |
| 軌道計算で発散する | 抗力により安定刻みが極端に小さくなる。抗力（密度）モデルを「なし」にする |

---

## 8. 関連ドキュメント

- 開発計画書: `desktop/PLAN.md`
- 物理モデル・テスト仕様: `range_calculator/SPEC.md`
- Web アプリ（同等機能のブラウザ版）: `webapp/README.md`
- 環境構築（Windows 11）: `docs/setup-windows.md`
- 環境構築（macOS / 共通）: `docs/setup-machine.md`
