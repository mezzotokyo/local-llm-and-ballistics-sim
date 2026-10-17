# desktop アプリ開発計画書 — 弾道シミュレーション（Windows/macOS ネイティブ GUI）

本計画書は、`range_calculator` の弾道シミュレーションを **デスクトップのネイティブ GUI** から
操作・可視化する `desktop/` アプリの開発計画を定義する。実装に着手する前の合意事項として
本ファイルを残し、実装後は `desktop/README.md` に利用手順を分離する。

---

## 1. 目的と背景

- `range_calculator/`（物理コア）と `webapp/`（ブラウザ UI + stdlib API）は既に存在し、
  物理計算は 133 件のテストで検証されている。
- 本計画の対象は、ブラウザを起動せずに単体で動く **デスクトップ GUI** を追加すること。
  物理計算は既存コアを再利用し、再実装しない。
- 対象 OS は **Windows 11（主）と macOS（副）**。配布は **実行ファイル**（Windows は
  `.exe`、macOS は `.app`。弾道用・軌道用の 2 つ）とする。

---

## 2. 技術選定

GUI フレームワークは **Python + Tkinter（ttk）** を採用する。

| 案 | mac 互換 | 既存資産の再利用 | 追加ツールチェーン | onefile 化 |
|----|---------|----------------|------------------|-------------|
| **Python + Tkinter（採用）** | 標準同梱 | 物理コアを直接 import | なし | PyInstaller |
| Tauri 2 | 可 | webapp の React を再利用 | Rust + Xcode | 内蔵バンドラ |
| .NET (WPF / WinUI 3) | 不可（Avalonia のみ可） | 物理コアを C# に移植 | dotnet SDK | 内蔵 |
| Python + PySide6 (Qt) | 可 | 物理コアを直接 import | pip 依存追加 | PyInstaller |

採用理由:

1. **stdlib only 方針との一致** — 本リポジトリの API・物理コアは標準ライブラリのみで動く。
   Tkinter は Windows/macOS の Python に同梱され、新規実行時依存を増やさない。
2. **物理コアの再利用** — `ballistics` / `physics_config` をそのまま import できる。
3. **クロスプラットフォーム** — 同一コードから Windows `.exe` / macOS `.app` を生成可能。
4. **グラフも自作** — webapp が自作 SVG で描くのと同様、`tkinter.Canvas` で描画し、
   追加のチャートライブラリを要しない。

トレードオフ: Tk の見た目は素朴である。モダンな外観が必須となった場合は Tauri への
移行を再検討する（本計画のスコープ外）。

---

## 3. スコープ

`webapp/README.md` の機能と同等とする。

- 入力: 初速（スライダー）、発射角（スライダー）、抗力係数 `Cd`（既定の球体 0.47 に固定）、
  刻み幅 `dt`（数値入力）、adaptive（トグル）、スピン回転数・スピン軸角（弾道のみ）、
  重力モデル（ニュートン / J2、軌道のみ）、抗力の密度モデル（なし / 一様 / 指数 / 区分指数）、
  軌道初期状態（半径・速度）
- 出力: 地表弾道では理想射程 / 実射程 / 低減率 / 飛行時間 / 着弾速度 / 積分ステップ数 /
  最短刻み（または刻み幅）/ 着弾有無、軌道では長半径 / 離心率 / 近点・遠点半径 /
  公転周期 / 軌道傾斜角 / 積分時間、時間上限到達時の警告
- 軌跡チャート: 抗力ありの軌跡、理想射程の破線、発射点・着弾点。軌道では原点
  （中心天体）を含む汎用ドメインで描画
- エラーは日本語で表示（物理コアの英語例外を変換）

スコープ外（将来検討）: プロファイル保存、CSV エクスポート、複数条件比較。

---

## 4. ディレクトリ構成

```
desktop/
  PLAN.md                # 本ファイル（開発計画）
  app_common.py          # 共有 GUI 基盤（queue / スレッド / メトリクス描画 / スライダー）
  ballistic_app.py       # 弾道ウィンドウ（エントリポイント）
  orbital_app.py         # 軌道ウィンドウ（エントリポイント）
  gui_model.py           # GUI 非依存の純ロジック（プリセット・検証・simulate グルー）
  trajectory_chart.py    # Canvas 製の軌跡チャート Widget（断面 x–y / 上面 x–z）
  errors.py              # 英語例外→日本語（server.py:67 の localize_error と同型）
  build.py               # PyInstaller を起動するビルドスクリプト（2 実行ファイル・追跡対象）
  README.md              # 起動・ビルド・mac 手順
  tests/
    test_gui_model.py    # 純ロジックの単体テスト（Tk 不要）
    test_trajectory_chart.py  # 軌跡チャートのスケーリング計算の単体テスト
    test_agreement.py    # server.py / lib/sim.ts との対応漏れ検出
```

`.gitignore` に `desktop/build/` と `desktop/dist/` を追記する。

---

## 5. 物理コアの再利用

`webapp/server/server.py` と同じ方式で、`range_calculator/` を `sys.path` に追加して
import する。

```python
REPO_ROOT = Path(__file__).resolve().parents[1]
RANGE_CALCULATOR = REPO_ROOT / "range_calculator"
if str(RANGE_CALCULATOR) not in sys.path:
    sys.path.insert(0, str(RANGE_CALCULATOR))

from ballistics import ProjectileSimulator, SimulationDiverged  # noqa: E402
from physics_config import DEFAULT_PARAMETERS  # noqa: E402
```

物理計算のロジックは再実装せず、既存の 133 件テストの庇護下に置く。軌跡は
`run_simulation(on_step=record)` の観測フックで収集する（`server.py:140` と同じ）。

---

## 6. UI 仕様（webapp との対応）

移植元は `webapp/src/lib/sim.ts`（共通定数・バリデーション）と `webapp/src/views/*`
（各画面）。弾道と軌道は別ウィンドウに分かれる。既定値・範囲・文言を一致させる。

| 項目 | 単位 | 既定値 | 範囲 / 選択肢 | 移植元 |
|------|------|--------|--------------|--------|
| 初速 | km/h | 170 | 10–500（スライダー） | `lib/sim.ts` |
| 発射角 | deg | 35 | 1–89（スライダー） | `lib/sim.ts` |
| 抗力係数 `Cd` | — | 0.47 | 固定（球体代表値、変更不可） | `lib/sim.ts` `DRAG_COEFFICIENT_DEFAULT` |
| 重力モデル | — | newtonian | newtonian / j2（弾道は constant 固定） | `gui_model.GRAVITY_PRESETS` |
| 密度モデル | — | 一様（弾道）/ なし（軌道） | なし / 一様 / 指数 / 区分指数 | `gui_model.DENSITY_PRESETS` |
| 軌道半径 `r` | m | 7.0e6 | 6.5e6–4.2e7（スライダー） | `gui_model.RADIUS_*` |
| 軌道速度 `v` | m/s | `sqrt(mu/r)` | 100–12000（自動追従可） | `gui_model.ORBITAL_SPEED_*` |
| 刻み幅 `dt` | s | 0.01（弾道）/ 1（軌道） | 0.0001–10、0.0001 単位 | `lib/sim.ts` |
| adaptive | — | off | チェックボックス | `views/*` |

抗力係数は既定の球体代表値 `Cd = 0.47` のみとし、プルダウン選択は廃止した
（`gui_model.DRAG_PRESETS` は既定値の同期検査用に 1 要素のみ保持し、
`webapp/src/lib/sim.ts` の `DRAG_PRESETS` と一致させる）。

| 値 | ラベル |
|----|--------|
| 0.47 | 球体（既定値） |

Result メトリクス（`webapp/src/views/*`）:

- 理想射程（抗力なし） m
- 実射程（抗力あり） m
- 到達距離の低減率 `(理想 - 実射程) / 理想 × 100` %
- 飛行時間 s
- 着弾速度 m/s
- 積分ステップ数
- 最短刻み（adaptive 時）/ 刻み幅（固定刻み時） s — 小数表示
- 着弾 yes / no

`timed_out` のときは「時間上限に達しました」警告を表示（`views/*`）。
dt のバリデーション文言（`lib/sim.ts`）も移植する。

---

## 7. 軌跡チャート（Canvas）

移植元は `webapp/src/components/TrajectoryChart.tsx`。ロジックを `tkinter.Canvas` に移植する。

- `niceStep` による目盛りの「切りの良い」刻み幅計算（`TrajectoryChart.tsx:13`）
- 軸・グリッド線と目盛りラベル
- 軌跡ポリライン（青、`#2f80ed`、線幅 2.5 相当）
- 理想射程の縦破線（オレンジ、`#f2994a`、破線）
- 発射点（緑 `#27ae60`）と着弾点（赤 `#eb5757`）のマーカー
- 軸ラベル（横: horizontal distance x (m)、縦: height y (m)）
- スケーリング: 地表弾道は `xDomain = maxX * 1.05`, `yDomain = maxY * 1.15`
  （`TrajectoryChart.tsx:43-44`）。軌道は原点（中心天体）を含み負座標も扱う汎用
  ドメイン（`chart_domain`）とし、`ideal_range` が無い場合は破線を描かない

---

## 8. 応答性（スレッド設計）

`dt = 0.0001` かつ `max_time = 300 s` では最大 300 万ステップとなり得るため、計算は
メインスレッドで行わない。

- ワーカースレッドで `simulate` を実行し、結果（または例外）を `queue.Queue` に渡す。
- `root.after()` によるポーリングで UI を更新し、計算中は「計算中...」を表示。
- 完了時に Result とチャートを更新、`timed_out` 警告・エラーを日本語で表示する。

---

## 9. 重複許容と対応漏れ防止

`server.py` との間に次の重複を **許容** する（各エントリポイントを自己完結させるため）。
ただし、片方だけ変更して他方が追随しない「対応漏れ」を、`tests/test_agreement.py` で
検出する。

| 重複対象 | 対応元 | 検出方法 |
|----------|--------|----------|
| 日本語エラー変換 | `webapp/server/server.py:67` `localize_error` | 代表的な英語メッセージ集合を両実装に通し、出力文字列の完全一致を assert |
| 抗力係数プリセット | `webapp/src/lib/sim.ts` `DRAG_PRESETS` | `sim.ts` を正規表現でパースし、値・ラベルの一致を assert |
| simulate グルー | `webapp/server/server.py:121` `simulate` | 基準シナリオ (170, 35, dt=0.01) を両者で実行し、主要メトリクスの一致を assert |

`gui_model.py` / `errors.py` の先頭コメントには「対応元パス」と「`test_agreement.py` が
同期を保証している」旨を明記し、編集者が更新漏れに気付けるようにする。

なお `test_range_calc.py:184` にソースを読み取って検査する前例があるため、
`lib/sim.ts` のパースによる同期検査は本リポジトリの慣例の範囲内である。

---

## 10. テスト方針

| 種別 | コマンド | 期待 |
|------|----------|------|
| desktop 純ロジック | `python3 -m unittest discover -s desktop/tests -p "test_*.py"` | 全パス（62 件） |
| 物理コア（既存） | `python3 -m unittest discover -s range_calculator -p "test_*.py"` | `Ran 133 tests` / `OK` |
| webapp API | `python3 -m unittest discover -s webapp/server -p "test_*.py"` | `Ran 17 tests` / `OK` |
| 文字混入検査 | `python3 tools/check_text_hygiene.py` | `0 finding(s)` |

GUI そのものはヘッドレスで検証しにくいため、検証可能なロジック（プリセット・dt 検証・
低減率計算・エラー変換・simulate グルー・チャートのスケーリング計算）を `gui_model.py` と
`trajectory_chart.py` に分離し、Tk に依存させずに単体テストする。

---

## 11. 実行ファイル化（Windows / macOS）

`desktop/build.py` が PyInstaller を起動する。弾道用・軌道用の 2 つを生成する。

- `--onefile --windowed`
- `--paths range_calculator`（非パッケージのコアモジュールを検出させる）
- `--add-data "range_calculator/config/physics_constants.json<pathsep>config"`
  - PyInstaller は非パッケージの `physics_config` をバンドル直下に展開するため、
    `Path(physics_config.__file__).parent / "config"` に一致するよう配置先を `config` とする。
  - `<pathsep>` は `os.pathsep`（Windows `;` / macOS `:`）で吸収する。
- 出力先は `desktop/dist/`（Windows `.exe` / macOS `.app`）。

実行時依存は標準ライブラリのみ。PyInstaller は **ビルド時のみ** のツールとし、venv で
`pip install pyinstaller` する手順を README に記載する。ビルド後の実行ファイルを起動し、
物理定数の config 警告が出ないことを確認する。

---

## 12. ドキュメント

- `desktop/README.md` を追加（起動 `python3 desktop/ballistic_app.py` / `orbital_app.py`、
  ビルド手順、macOS 差異）。
- `docs/setup-windows.md` と `range_calculator/SPEC.md` 第11章に desktop の一行を追記
  （Python のみで動作し、追加の実行時依存が無い旨）。

---

## 13. 実装順序

1. `gui_model.py` / `errors.py`（純ロジック）と `tests/test_gui_model.py`
2. `trajectory_chart.py`
3. `app_common.py` + `ballistic_app.py` / `orbital_app.py`（UI・スレッド）
4. `tests/test_agreement.py`（対応漏れ防止）
5. `build.py` + `desktop/README.md` + `docs` 追記 + `.gitignore`
6. 全テスト・文字混入検査・実機起動確認

---

## 14. 未確定事項

- ディレクトリ名は `desktop/` で確定（macOS 互換を踏まえた命名）。
- `server.py` とのロジック重複は許容し、対応漏れはテストで検出する方針で確定。
- PyInstaller の導入はビルド時のみ（venv で `pip install`）で確定。

---

## 15. 拡張: 重力・抗力モデルと軌道

`range_calculator` の摂動拡張（SPEC.md §2.2 / §2.2(b)）に GUI を追随させた。

- 重力モデルは `constant`（地表） / `newtonian`（中心重力） / `j2`（+地球扁平）。
  中心重力では初期状態を **円軌道**（半径 `r`、速度 `sqrt(mu/r)`、位置は +x 軸上）
  で与える。速度は自動追従を既定とし、手動指定も可能。閉軌道は **1周期**（周期 × 1.05）
  を自動積分し、刻み幅は周期 / 4000 を上限に丸める（既定の `dt=0.01` のままだと 1周で
  約60万ステップ・約30秒かかるため）。着弾が無い軌道では時間上限警告を表示しない。
- 密度モデルは `none`（抗力無効、`Cd=0`）/ `constant` / `exponential` / `tabulated`。
  軌道では抗力により安定刻みが極端に小さくなるため「なし」を既定の推奨とする
  （重力を中心重力へ切り替えると密度を「なし」へ自動変更する）。
- Result パネルは弾道（射程系）と軌道（軌道要素系）で行構成を切り替える
  （`gui_model.result_metrics`）。初期表示は弾道のプレースホルダ
  （`gui_model.DEFAULT_METRIC_ROWS`）。
- UI 組み立ては `gui_model` の純関数（`gravity_label` / `density_label` /
  `orbital_speed` / `make_conditions` / `format_optional` / `result_metrics`）を
  呼ぶだけに留め、Tk 非依存でテストする。
- チャートは `chart_domain` / `axis_ticks` を追加し、軌道（負座標・原点）に
  対応。純関数として `tests/test_trajectory_chart.py` で検証する。

---

*最終更新: 初版作成（2026-10-10）/ 摂動・軌道対応を追記（2026-10-17）*
