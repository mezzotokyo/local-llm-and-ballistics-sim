# LLM支援と弾道シミュレーションの統合プロジェクト

このリポジトリは、ローカル LLM 推論サーバー（Ollama）を opencode から利用する開発支援と、
物理モデルの弾道シミュレーション（range_calc）を統合したプロジェクトです。

- **シミュレーションコア**: `range_calculator/` 内に配置。物理計算に特化し、他の言語への依存を極力排除しています。
- **開発サポート**: opencode を介して LLM と連携し、開発を支援します。

等質・球形の弾丸を水平面に対して角度 θ、初速 `v0` で発射したとき、速度の 2 乗に
比例する空気抵抗（抗力）を考慮して**地面衝突までの距離と飛行時間**を数値積分で求めます。

> 本ツールは**到達距離の相対比較と傾向分析**のためのものであり、実測弾道
> データとの絶対一致や競技規則的精度を要求する用途には用いません
> （適用限界は `range_calculator/SPEC.md` 第7章に詳細）。

各機能の詳細は、それぞれのドキュメント（§6）を参照してください。

---

## 1. プロジェクト構成

リポジトリは機能ごとに次のディレクトリで構成されています。

| ディレクトリ | 対象機能 | 特徴 | 主なドキュメント |
| :--- | :--- | :--- | :--- |
| `range_calculator/` | 弾道シミュレーション（コア） | 物理計算に特化。他の言語への依存を極力排除し、Python の標準ライブラリのみで動作します。 | `SPEC.md` |
| `webapp/` | Web UI | ブラウザで操作・可視化します。Python 標準ライブラリの JSON API を利用します。 | `webapp/README.md` |
| `desktop/` | ネイティブ GUI | Python 標準ライブラリの Tkinter を用いた、ブラウザ不要な実行環境を提供します。 | `desktop/README.md` |
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

`range_calculator/SPEC.md` の要点です。

### 3.1 基礎方程式

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
| `mu` | 中心天体の標準重力パラメータ G·M（球面重力モデル用） | 3.986004418e14 m³/s² |
| `J2` | 扁平率摂動の第2帯球係数（`j2_gravity()` 用） | 1.08263e-3 |

重力は加速度場として差し替えられます（`constant_gravity()` / `newtonian_gravity(mu)` /
`j2_gravity(mu, J2, R)`）。`newtonian_gravity()` は原点へ向かう逆二乗則 `a = -mu·r/|r|³` を
与え、`ProjectileSimulator.from_state()` と `ground_collision=False` を組み合わせて軌道計算に
使います。`j2_gravity()` はさらに扁平（第2帯球）摂動 `a_J2` を加え、`sum_fields(*fields)` は
複数の加速度場を合成して多体問題へ拡張できます。ニュートン重力での軌道は `orbital.py` の
`orbital_elements()` で軌道要素（長半径・離心率・近点/遠点・周期・傾斜角）に換算できます。

抗力も加速度場（`DragModel`）として差し替えられ、高度依存の大気密度
（`DensityModel`: `constant_density` / `exponential_density` / `tabulated_density`）を
`atmospheric_drag()` と組み合わせて軌道減衰を扱えます。

### 3.2 数値解法

- **固定刻みモード**: `dt`（既定 0.01 s）固定。局所誤差 `O(dt⁵)`
- **適応刻みモード（`adaptive=True`）**: 安定性上限 `dt_max = 0.5 / (k·|v|)` を
  超えないよう必要時にのみ刻みを短縮（発散防止機構。精度向上は保証しない）
- 地面衝突（`y = 0`）はステップ内を**線形補間**して確定
- 発散検出・時間上限（既定 300 s）・初心者向けの数値ガードあり

### 3.3 基準シナリオ（`170 km/h`, `35°`, `dt=0.01`）

| 指標 | 値 |
|------|-----|
| 理想射程（抗力なし） | 213.60 m |
| 実射程（抗力あり） | 101.12 m |
| 飛行時間 | 4.37 s |
| 抗力による低減率 | 約 52.7 % |

---

## 4. 利用形態

### 4.1 CLI（`range_calculator/range_calc.py`）

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

### 4.2 Web アプリ（`webapp/`）

Vite + React + TypeScript のフロントと、Python 標準ライブラリのみの JSON API
（`stdlib`）で構成。物理計算はコアを再利用します。

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
パッケージなしで動作し、PyInstaller で実行ファイル（弾道用・軌道用の 2 つ）をビルドできます。

```sh
python3 desktop/ballistic_app.py   # 弾道ウィンドウ
python3 desktop/orbital_app.py     # 軌道ウィンドウ
```

詳細: `desktop/README.md`

---

## 5. 検証・品質

- **物理コアのテスト**: 133 件（`test_range_calc.py` 58 件 + `test_adaptive_timestep.py` 39 件 + `test_orbital.py` 36 件）
  - 解析解（`k=0`）との一致 / 収束性 / 着弾状態 / 回帰 / パラメータ検証 /
    シミュレータ契約 / 数値ガード / Magnus 揚力 / ニュートン・J2 重力 / 軌道要素 / 密度・抗力モデル
- **desktop のテスト**: 62 件（GUI 純ロジック・軌跡チャート・webapp との対応漏れ検査）
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
| `range_calculator/SPEC.md` | 物理モデル仕様・テスト仕様・適用限界 |
| `range_calculator/HISTORY.md` | 変更履歴（V0〜V5 の変遷） |
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

