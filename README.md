# LLM支援と物理シミュレーションの統合プロジェクト

このリポジトリは、ローカル LLM 推論サーバー（Ollama）を opencode から利用する開発支援と、
物理シミュレーション（弾道・軌道・多体）を統合したプロジェクトです。

- **シミュレーションコア**: `range_calculator/` 内に配置。弾道・軌道・多体（N 体）の物理計算に
  特化し、他の言語への依存を極力排除しています。
- **開発サポート**: opencode を介して LLM と連携し、開発を支援します。

単純な弾道計算にとどまらず、次の 3 つの物理モデルを共通コアで扱います。

- **弾道**: 抗力とスピン（Magnus 揚力）を考慮した射程・飛行時間（§3.1）
- **軌道**: 中心重力（ニュートン / J2 扁平）と高度依存大気による軌道減衰（§3.2）
- **多体（N 体）**: 相互重力（直接 O(N²)・RK4）による天体の運動（§3.3）

> 本ツールは**物理挙動の相対比較と傾向分析**のためのものであり、実測データとの
> 絶対一致や競技規則的精度を要求する用途には用いません
> （適用限界は `range_calculator/SPEC.md` 第14章（弾道）・第22章（軌道）・第30章（多体）に詳細）。

各機能の詳細は、それぞれのドキュメント（§6）を参照してください。

---

## 1. プロジェクト構成

リポジトリは機能ごとに次のディレクトリで構成されています。

| ディレクトリ | 対象機能 | 特徴 | 主なドキュメント |
| :--- | :--- | :--- | :--- |
| `range_calculator/` | 物理シミュレーション（コア） | 弾道・軌道・多体（N 体）の 3 モデルを 1 つのコアで提供。物理計算に特化し、他の言語への依存を極力排除した Python 標準ライブラリのみで動作します。 | `SPEC.md` |
| `webapp/` | Web UI（弾道・軌道） | ブラウザで操作・可視化します。Python 標準ライブラリの JSON API を利用します（多体は対象外）。 | `webapp/README.md` |
| `desktop/` | ネイティブ GUI（弾道・軌道・多体） | Python 標準ライブラリの Tkinter を用いた、ブラウザ不要な実行環境を提供します。多体のみこちらで操作できます。 | `desktop/README.md` |
| `docs/` | 環境構築・セットアップ手順 | macOS / Linux / Windows / Ollama 構築の手順を格納します。 | §6 を参照 |
| `tools/` | 開発支援ツール | 文字混入検査、ブートストラップ（`bootstrap.sh`）など、開発サイクルを補助するユーティリティ群です。 | — |
| `.githooks/` | pre-commit フック | コミット時に文字混入検査を自動実行します。 | — |
| `opencode.json` | LLM プロバイダ設定 | opencode が利用する LLM プロバイダ（Ollama）の設定ファイルです。 | `docs/setup-ollama-server.md` |

---

## 2. 環境構築

### 2.1 前提

| ソフト | 用途 | 備考 |
|--------|------|------|
| Python 3.9 以上 | 物理コア・テスト・文字混入検査 | 標準ライブラリのみ。3.15 で検証 |
| Node.js 20.19+ / 22.12+ | `webapp` の開発サーバ・ビルド | Vite 8 の要件。`webapp` 以外は不要 |
| Ollama | ローカル LLM 推論サーバー | opencode から OpenAI 互換 API で接続 |

環境構築の詳細は以下を参照してください。

- **macOS / Linux / 共通**: `docs/setup-machine.md`
- **Windows 11（Scoop）**: `docs/setup-windows.md`
- **Ollama 推論サーバー（macOS / Windows）**: `docs/setup-ollama-server.md`

### 2.2 LLM 推論サーバーの構築（Ollama）

開発用エージェントには **opencode**、LLM プロバイダーには**オープンソースの
Ollama** を使用します。LLM プロバイダーは **LAN 内のサーバー上に構築**する想定です。

> **サーバーとクライアントを同居させない。**
> 推論サーバーと開発クライアントを同一マシン上に載せると、モデルのメモリ使用量と
> ビルド・エディタ・エージェントの負荷が重なり、マシンメモリの逼迫により動作が
> 重くなります。そのため、サーバーは開発マシンとは別に LAN 上へ構築します。

サーバー環境を構築しない場合でも、opencode が提供する**無料モデル**や、
契約済みのプロバイダーを利用することも可能です。

Ollama は既定で `127.0.0.1:11434` にしかバインドしないため、**LAN 公開には
`OLLAMA_HOST=0.0.0.0:11434` の設定が必須**です。開発クライアントからいつでも
接続できるよう、サーバーは**常駐化**（macOS: LaunchDaemon ／ Windows: サービス）
し、`OLLAMA_HOST` は常駐プロセスの環境変数として設定します（ログアウト・再起動後も
自動起動）。具体的な設定手順は `docs/setup-ollama-server.md` を参照してください。

モデルの取得:

```sh
ollama pull gemma4:e4b-mlx    # opencode.json の gemma4:e4b-mlx 系のベースモデル
ollama pull qwen3.5:4b-mlx    # qwen3.5:4b-mlx-64k のベースモデル
ollama list
```

詳細な手順（Modelfile でのエイリアス作成・ファイアウォール設定・疎通確認）は
`docs/setup-ollama-server.md` を参照してください。

### 2.3 pre-commit フックの有効化

クローンごとに一度だけ:

```sh
bash tools/bootstrap.sh .
```

または、`git config core.hooksPath .githooks` のみでも有効です（クローン済みの場合）。
以降、コミット時に文字混入検査が自動実行されます。

### 2.4 AI 開発支援（opencode）

`opencode.json` で Ollama の推論サーバーを参照しています。プロバイダ定義と
モデル一覧は同ファイル、サーバー構築手順は `docs/setup-ollama-server.md` を
参照してください。

Ollama サーバーを構築しない場合は、opencode が提供する**無料モデル**を利用
するか、**契約済みのプロバイダー**（API キー等）を `opencode.json` に定義して
切り替えることができます。

### 2.5 新規リポジトリの作成（雛形配布）

複数プロジェクトを扱う場合、**プロジェクト単位でリポジトリを分離**します。
本リポジトリは雛形（テンプレート）として、`tools/bootstrap.sh` で各新リポジトリへ
pre-commit フック・文字混入検査・`.gitattributes`・`.gitignore` 一式を配布できます。

```sh
# 1. ホストで空リポジトリを作成（GitHub の場合）
gh repo create <名前> --private

# 2. クローン
git clone <new-origin> 新しいプロジェクト && cd 新しいプロジェクト

# 3. 雛形を配布（既存リポジトリのパスを指定）
bash /path/to/本リポジトリ/tools/bootstrap.sh .

# 4. 初期ファイルをコミットして push
git add . && git commit -m "init" && git push -u origin main
```

`opencode.json` はプロジェクト単位の設定です。opencode はグローバル設定
（`~/.config/opencode/opencode.json`）とプロジェクト設定をマージして読み込むため、
新リポジトリでも同じ LLM プロバイダ設定を使う場合は、このファイルをコピーするか、
グローバル設定に同等の内容を定義してください。

---

## 3. 物理モデル概要

`range_calculator/SPEC.md` の要点です。共通コアが次の 3 モデルを提供し、いずれも
加速度場（重力・抗力・揚力）を合成して陽的 4 次ルンゲ–クッタ（RK4）で積分します。

| モデル | 対象 | 主な機能 |
|--------|------|----------|
| 弾道（§3.1） | 地表付近の射出体 | 抗力、スピン（Magnus 揚力）、着弾・射程の計算 |
| 軌道（§3.2） | 中心重力場の天体 | ニュートン重力 / J2 扁平、高度依存大気による軌道減衰、軌道要素への換算 |
| 多体（§3.3） | 複数天体の相互重力 | 完全 N 体（直接 O(N²)）、フレーム記録と再生 |

### 3.1 弾道（抗力・スピン）

等質・球形の弾丸を水平面に対して角度 θ、初速 `v0` で発射したとき、速度の 2 乗に比例する
空気抵抗（抗力）を考慮して**地面衝突までの距離と飛行時間**を数値積分で求めます。
質量で割った加速度形式の 6 元状態 `(x, y, z, vx, vy, vz)` を陽的 4 次ルンゲ–クッタ（RK4）で
積分します。重力は鉛直下向き `-y` 方向のみに作用し、横方向 `z` はスピン（Magnus 揚力）による
左右のずれを表します（スピン 0 では常に 0）。

```text
dx/dt  = vx
dy/dt  = vy
dz/dt  = vz
dvx/dt = -k · vx · |v|
dvy/dt = -k · vy · |v| - g
dvz/dt = -k · vz · |v|

|v| = sqrt(vx² + vy² + vz²)
```

| 記号 | 意味 | 既定値 |
|------|------|--------|
| `g` | 重力加速度 | 9.81 m/s² |
| `ρ` | 空気密度 | 1.225 kg/m³ |
| `Cd` | 抗力係数 | 0.47（球体代表値。既定値に固定） |
| `m` | 弾丸質量 | 0.149 kg |
| `d` | 弾丸直径 | 0.075 m |
| `k` | 抗力係数 `= 0.5·ρ·A·Cd / m` | 8.535522e-03 m⁻¹ |

#### 基準シナリオ（`170 km/h`, `35°`, `dt=0.01`）

| 指標 | 値 |
|------|-----|
| 理想射程（抗力なし） | 213.60 m |
| 実射程（抗力あり） | 101.12 m |
| 飛行時間 | 4.37 s |
| 抗力による低減率 | 約 52.7 % |

### 3.2 軌道（中心重力・J2・大気）

重力は加速度場として差し替えられます（`constant_gravity()` / `newtonian_gravity(mu)` /
`j2_gravity(mu, J2, R)`）。`newtonian_gravity()` は原点へ向かう逆二乗則 `a = -mu·r/|r|³` を
与え、`ProjectileSimulator.from_state()` と `ground_collision=False` を組み合わせて軌道計算に
使います。`j2_gravity()` はさらに扁平（第2帯球）摂動 `a_J2` を加えます。ニュートン重力での
軌道は `orbital.py` の `orbital_elements()` で軌道要素（長半径・離心率・近点/遠点・周期・
傾斜角）に換算できます。

| 記号 | 意味 | 既定値 |
|------|------|--------|
| `mu` | 中心天体の標準重力パラメータ G·M（球面重力モデル用） | 3.986004418e14 m³/s² |
| `J2` | 扁平率摂動の第2帯球係数（`j2_gravity()` 用） | 1.08263e-3 |

抗力も加速度場（`DragModel`）として差し替えられ、高度依存の大気密度
（`DensityModel`: `constant_density` / `exponential_density` / `tabulated_density`）を
`atmospheric_drag()` と組み合わせて軌道減衰を扱えます。

### 3.3 多体問題（相互重力）

`range_calculator/nbody.py` は完全 N 体の相互重力（点質量）を陽的 4 次 RK4 で積分します。
各天体は標準重力パラメータ `mu = G*M` と状態 `(x,y,z,vx,vy,vz)` を持ち、

```text
a_i = sum_{j != i} mu_j · (r_j - r_i) / |r_j - r_i|^3
```

を解きます（直接 O(N²)）。複数の加速度場は `sum_fields(*fields)` で合成し、軌道の摂動
（J2・大気）と同じ枠組みで多体へ拡張しています。点質量・衝突非対応で、長期積分では
RK4 のエネルギー漂移に注意が必要です。

### 3.4 数値解法

- **固定刻みモード**: `dt`（既定 0.01 s）固定。局所誤差 `O(dt⁵)`
- **適応刻みモード（`adaptive=True`）**: 安定性上限 `dt_max = 0.5 / (k·|v|)` を
  超えないよう必要時にのみ刻みを短縮（発散防止機構。精度向上は保証しない）
- 地面衝突（`y = 0`）はステップ内を**線形補間**して確定（軌道モードは
  `ground_collision=False` で衝突判定しない）
- 発散検出・時間上限（既定 300 s）・初心者向けの数値ガードあり
- **多体（N 体）**: 既定は**固定刻み RK4**。`adaptive=True` では `dt` を上限とし、
  最短ペア周期の `1 / ADAPTIVE_STEPS_PER_PERIOD`（既定 100 ステップ／周）まで各ステップを
  短縮する（発散防止かつ 1 周あたりのエネルギー漂移を約 1e-6 に抑える。精度保証ではない）。
  GUI 側では推定ステップ数を 500,000 に上限して確認し（`MAX_NBODY_STEPS`。系外惑星の
  多数周回を想定）、`dt` が最短ペア周期に対して粗すぎる場合は発散を警告する
  （`nbody_timestep_warning`。adaptive 時は短縮するため警告しない）

---

## 4. 利用形態

### 4.1 CLI（`range_calculator/range_calc.py`）

弾道・軌道（ニュートン / J2）の 2 モデルをコマンドラインから実行します。

```sh
python3 range_calculator/range_calc.py [scenario_path] [dt_max] [--adaptive] [--v0=<km/h>] [--angle=<deg>]
python3 range_calculator/range_calc.py --spin=<rpm> [--spin-axis=<deg>] [--v0=<km/h>] [--angle=<deg>]
python3 range_calculator/range_calc.py --orbital [--radius=<m>] [--v0=<km/h>] [--adaptive] [--j2] [--atmosphere]
```

```sh
python3 range_calculator/range_calc.py                      # 既定シナリオ（data.csv）
python3 range_calculator/range_calc.py data.csv 0.01 --adaptive --v0=170 --angle=35
python3 range_calculator/range_calc.py --spin=3000 --spin-axis=0   # バックスピンと横ずれ
python3 range_calculator/range_calc.py --orbital --radius=7.0e6 --v0=27166   # 円軌道と軌道要素
python3 range_calculator/range_calc.py --orbital --v0=27166 --j2 --atmosphere  # J2 + 大気
```

`--spin` は弾道に任意の Magnus 揚力（スピン）を有効にします（`--spin-axis` は回転軸角）。
`--orbital` は中心重力場（`newtonian_gravity`）で軌道を積分し、軌道要素を出力します。
`--j2` で扁平摂動（`j2_gravity`）、`--atmosphere` で区分指数大気による抗力減衰を有効にします。

> **多体（N 体）には CLI は用意していません。** 入力が多いため、`python3` から
> `range_calculator.nbody.NBodySimulator` を直接呼び出すか、専用のデスクトップ GUI
> （§4.3 `nbody_app.py`）を使ってください。

### 4.2 Web アプリ（`webapp/`）

Vite + React + TypeScript のフロントと、Python 標準ライブラリのみの JSON API
（`stdlib`）で構成。物理計算はコアを再利用します。**弾道・軌道の 2 画面**で、
多体（N 体）は Web アプリでは扱いません（対象は desktop のみ。`desktop/PLAN.md` §16）。

```sh
# ターミナル A: API サーバ
python3 webapp/server/server.py --port 8000

# ターミナル B: フロント（別ターミナル）
cd webapp && npm run dev
# → http://127.0.0.1:5173/
```

詳細: `webapp/README.md`

### 4.3 デスクトップ GUI（`desktop/`）

Python 標準ライブラリの Tkinter（ttk）によるネイティブ GUI。追加の `pip`
パッケージなしで動作し、PyInstaller で実行ファイル（弾道用・軌道用・多体用の 3 つ）を
ビルドできます。**3 モデルすべて**に対応します（弾道・軌道は CLI / Web もあるが、
多体（N 体）は GUI 専用）。

```sh
python3 desktop/ballistic_app.py   # 弾道ウィンドウ
python3 desktop/orbital_app.py     # 軌道ウィンドウ
python3 desktop/nbody_app.py       # 多体（N-body）ウィンドウ
```

詳細: `desktop/README.md`

---

## 5. 検証・品質

- **物理コアのテスト**: 200 件（`test_range_calc.py` 58 件 + `test_adaptive_timestep.py` 39 件 + `test_orbital.py` 36 件 + `test_nbody.py` 67 件）
  - 解析解（`k=0`）との一致 / 収束性 / 着弾状態 / 回帰 / パラメータ検証 /
    シミュレータ契約 / 数値ガード / Magnus 揚力 / ニュートン・J2 重力 / 軌道要素 /
    密度・抗力モデル / 相互重力（N 体）
- **desktop のテスト**: 133 件（GUI 純ロジック・軌跡チャート・多体（N-body）ロジック・webapp との対応漏れ検査）
- **webapp/server のテスト**: 17 件（`gravity_model` / `drag_model` / 軌道要素 / スピン API）
- **文字混入検査**: `python3 tools/check_text_hygiene.py`
  （`0 finding(s)` が正常。pre-commit フックに組み込み）

```sh
python3 -m unittest discover -s range_calculator -p "test_*.py"
python3 -m unittest discover -s desktop/tests -p "test_*.py"
python3 -m unittest discover -s webapp/server -p "test_*.py"
python3 tools/check_text_hygiene.py
```

> **注意**: テストはフラット import（`import ballistics` 等）を使うため、カレント
> ディレクトリに注意してください（リポジトリルートから実行します）。

---

## 6. ドキュメント

| ドキュメント | 内容 |
|--------------|------|
| `range_calculator/SPEC.md` | 物理モデル仕様（弾道・軌道・多体）・テスト仕様・適用限界 |
| `range_calculator/HISTORY.md` | 変更履歴（V0〜V5 の変遷と、V5 以降の軌道・多体・UI 拡張） |
| `webapp/README.md` | Web アプリの起動・API・構成 |
| `desktop/README.md` | デスクトップ GUI の起動・ビルド・テスト |
| `desktop/PLAN.md` | デスクトップアプリの開発計画書 |
| `docs/setup-machine.md` | 環境構築（macOS / Linux / 共通） |
| `docs/setup-windows.md` | 環境構築（Windows 11 / Scoop） |
| `docs/setup-ollama-server.md` | Ollama 推論サーバー構築（opencode 接続用） |
| `LICENSE` | ライセンス全文（MIT） |
| `THIRD_PARTY_NOTICES.md` | 依存コンポーネントのライセンス・配布時の注意 |

---

## 7. ライセンス

本リポジトリは **MIT License** の下で公開されています。全文は [`LICENSE`](LICENSE) を参照してください。

```text
Copyright (c) 2026 HAYAKAWA
```

同梱・依存コンポーネント（React / Vite / TypeScript / Python / Tcl-Tk / PyInstaller など）の
ライセンスと、実行ファイル等を配布する際の注意点は
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) にまとめています。

開発用の非公開リポジトリ（`origin`）と公開リポジトリ
（`mezzotokyo/local-llm-and-ballistics-sim`）は同じソースを共有し、ライセンスは
公開側に対して付与されます。

