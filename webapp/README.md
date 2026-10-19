# Range Calculator Web (webapp)

`range_calculator` の物理シミュレーション（**弾道・軌道**）をブラウザで操作・可視化する
Web アプリです。フロントエンドは Vite + React + TypeScript、バックエンドは Python 標準ライブラリのみの
JSON API で構成され、物理計算は既存の `range_calculator`（`ballistics` / `orbital` /
`physics_config`）をそのまま再利用します。

多体（N 体）は Web アプリの対象外です。操作したい場合は `desktop/nbody_app.py` を
使ってください（`desktop/PLAN.md` §16）。

---

## 1. 機能

### 1.1 入力（Launch conditions）

画面上部のタブで **弾道** と **軌道** を切り替えます。入力欄はタブごとに分かれています。

#### 弾道タブ

| 項目 | 単位 | 既定値 | 説明 |
|------|------|--------|------|
| 初速 | km/h | 170 | スライダー（10–500） |
| 発射角 | deg | 35 | スライダー（1–89） |
| 抗力係数 `Cd` | — | 0.47 | 固定（球体代表値）。変更不可 |
| 抗力（密度）モデル | — | 一様 | なし / 一様 / 指数（高度依存）/ 区分指数（0–1000 km） |
| スピン回転数 | rpm | 0 | スライダー（0–6000）。Magnus 揚力の大きさ |
| スピン軸角 | deg | 0 | スライダー（-180–180）。0 でバックスピン、+90 で *+z*、−90 で *−z*、±180 でトップスピン |
| 刻み幅 `dt` | s | 0.01 | 数値入力（0.0001–10、0.0001 単位） |
| adaptive | — | off | 安定性上限で刻みを自動短縮するモード |
| 表示 | — | 断面 (x–y) | 断面 (x–y) / 上面 (x–z)（スピンによる左右のずれ） |

#### 軌道タブ

| 項目 | 単位 | 既定値 | 説明 |
|------|------|--------|------|
| 重力モデル | — | newtonian | ニュートン（軌道）/ ニュートン+J2（軌道） |
| 軌道半径 `r` | m | 7.0e6 | スライダー（6.5e6–4.2e7） |
| 軌道速度 `v` | m/s | `sqrt(mu/r)` | スライダー（100–12000）。「円軌道速度を自動設定」で `r` に追従 |
| 抗力係数 `Cd` | — | 0.47 | 固定（球体代表値）。変更不可 |
| 抗力（密度）モデル | — | なし | なし / 一様 / 指数 / 区分指数 |
| 刻み幅 `dt` | s | 1 | 数値入力（0.0001–10、0.0001 単位） |
| adaptive | — | off | 安定性上限で刻みを自動短縮するモード |

抗力係数 `Cd` は既定プロファイルの球体代表値 `0.47` に固定しており、UI からは変更できません。
`parameters.drag_coefficient` として `0.47` を API に送信します。プリセット選択は廃止しました
（`range_calculator/SPEC.md` 第14章）。

「シミュレーション実行」ボタンで API を呼び出します。実行のたびに Result と軌跡は
クリアされ、結果が得られた時点で表示されます。エラー時は Result を表示せず、
日本語のエラーメッセージを表示します。

### 1.2 出力メトリクス（Result）

弾道タブでは:

- 理想射程（抗力なし）: 閉形式 `v0^2 sin(2θ) / g`
- 実射程（抗力あり）: RK4 による着弾距離
- 到達距離の低減率: `(理想 - 実射程) / 理想 × 100` %
- 飛行時間
- 着弾速度
- 横方向のずれ z（スピンによる左右のずれ。値は `|z|`）
- 積分ステップ数
- 最短刻み / 刻み幅（計算に使用された刻み幅。`adaptive` 有効時は「最短刻み」=最小の刻み幅、
  無効時は「刻み幅」=固定刻み幅として表示。`adaptive` の有無にかかわらず常時表示。小数で表示）
- 着弾したかどうか

軌道タブでは、射程系の代わりに軌道要素を表示します:

- 長半径 `a` / 離心率 `e` / 近点半径 `r_p` / 遠点半径 `r_a` / 公転周期 `T` / 軌道傾斜角 `i`
- 積分時間 / 積分ステップ数 / 最短刻み（または刻み幅）
- 開軌道では `a` / `r_a` / `T` は `-` 表示

時間上限（既定 300 s）に達した場合は警告を表示します。

### 1.3 軌跡チャート

独立した計算を行わず、シミュレーション中の各ステップを取得して SVG で描画します。

- 青い実線: 抗力ありの軌跡（横軸 x、縦軸 y。上面表示では縦軸 z）
- オレンジの破線: 理想射程（抗力なし）の位置（軌道では非表示）
- 緑の点: 発射点 / 赤の点: 着弾点（軌道では着弾点を描かず、代わりに原点＝中心天体を表示）
- 依存するチャートライブラリは無し（自作 SVG）

弾道タブは「断面 (x–y)」と「上面 (x–z)」（スピンによる左右のずれ）を切り替えられます。

地表弾道は原点を左下に固定した従来スケーリング（`x*1.05`, `y*1.15`）で描きます。軌道は
原点（中心天体）を含み負座標も扱う汎用ドメインで描きます。

### 1.4 API

| メソッド | パス | 説明 |
|----------|------|------|
| GET | `/api/health` | 死活確認（`{"status":"ok"}`） |
| GET | `/api/config` | 既定値と物理定数の既定プロファイル |
| POST | `/api/simulate` | 1回の発射を実行し、メトリクスと軌跡を返す |

`POST /api/simulate` のリクエスト例:

```json
{
  "velocity_kmph": 170,
  "angle_deg": 35,
  "dt": 0.01,
  "adaptive": false,
  "parameters": {
    "drag_coefficient": 0.47
  }
}
```

任意で `parameters` オブジェクト（`max_time`, `gravity`, `mu`, `j2`, `equatorial_radius`,
`scale_height`, `sea_level_density`, `air_density`, `mass`, `diameter`, `drag_coefficient`）を
指定すると物理定数を上書きできます。UI は `drag_coefficient` を既定プロファイルの球体代表値
`0.47`（§1.1）に固定して送信します。省略時は同じ既定プロファイル（`Cd=0.47`）が使われます。軌跡は最大 2000 点に
間引きして返します。`GET /api/config` は既定値、物理定数、`gravity_models` /
`drag_models` の一覧を返します。

#### 中心重力モード（軌道計算）

`gravity_model` に `"newtonian"` または `"j2"` を指定すると、地表弾道の代わりに中心重力場
（`newtonian_gravity`、`mu`。`"j2"` ではさらに扁平摂動 `j2_gravity`）で軌道を積分します
（`ground_collision=False`）。このモードでは `velocity_kmph` / `angle_deg` の代わりに
`initial_state`（`[x, y, z, vx, vy, vz]` の 6 要素）が必須です。応答には `orbital` ブロックが
付き、軌道要素（`specific_energy`, `semi_major_axis`, `eccentricity`, `periapsis`,
`apoapsis`, `period`, `inclination_deg`。開軌道では `apoapsis` / `period` が `null`）
を返します。`"constant"`（既定）では `orbital` は `null` です。

閉軌道では **1周期**（周期 × 1.05）を自動積分し、軌道が一周して閉じます（`max_time` を
明示指定した場合はそちらが優先されます）。このとき刻み幅は周期 / 4000 を上限に丸めます
（既定の `dt=0.01` では 1周に約60万ステップ・約30秒かかるため）。着弾が無い軌道では
時間上限警告（`timed_out`）は UI に表示しません。

任意で `drag_model`（`"constant"`（既定）/ `"exponential"` / `"tabulated"`）を指定すると、
抗力の密度を高度依存にできます。`"exponential"` は `scale_height` / `sea_level_density` の
単一指数、`"tabulated"` は 0–1000 km の区分指数テーブル（`EARTH_ATMOSPHERE_LAYERS`）を
使います。高度は軌道モードでは `|r| - equatorial_radius`、地表弾道では `y` です。

```json
{
  "gravity_model": "newtonian",
  "drag_model": "constant",
  "dt": 1.0,
  "parameters": { "drag_coefficient": 0.0 },
  "initial_state": [7000000, 0, 0, 0, 7546.053, 0]
}
```

エラー時は HTTP 400（入力値の不正）または 422（計算の発散）と
`{"error": "<メッセージ>"}` を返します。`error` は日本語で、刻み幅が粗すぎる場合などは
許容値（例: `dt を 1.24049 未満にしてください`）を含みます。

---

## 2. 構成

```text
webapp/
  index.html
  package.json
  vite.config.ts        # dev サーバ設定（IPv4 固定・/api プロキシ）
  src/
    main.tsx
    App.tsx             # 上部ナビ（弾道 / 軌道）のシェル
    lib/
      sim.ts            # 共通定数・リクエスト生成・メトリクス整形
    views/
      BallisticView.tsx # 弾道ビュー
      OrbitalView.tsx   # 軌道ビュー
    api.ts              # fetch ラッパー
    types.ts            # API 型定義
    components/
      TrajectoryChart.tsx  # 断面 xy / 上面 xz
  server/
    server.py           # stdlib のみの JSON API
```

開発時はフロント（5173）から API（8000）へ、Vite の dev プロキシ経由でアクセスします
（同一オリジンになるため CORS 設定は不要）。

---

## 3. 前提環境

いずれの OS でも必要なもの:

- **Python 3.9 以上**（Windows: `python` / `python3`、macOS: `python3`）
  - 追加の `pip` パッケージは不要。API と物理コアは標準ライブラリのみで動作します
- **Node.js 20.19 以上 / 22.12 以上**（Vite 8 の要件）と npm
  - `npm install` で React・Vite・TypeScript 等の依存は自動導入されます

### 3.1 Windows（Scoop）

未導入なら次で導入します（`docs/setup-windows.md` と同じ構成。`opencode` は任意）。

```powershell
scoop install git python gh nodejs
```

Scoop 導入直後の古いシェルでは PATH が未反映の場合があります。新しい PowerShell を
開くか、次を実行してください。

```powershell
$env:Path += ";$env:USERPROFILE\scoop\shims"
```

### 3.2 macOS

- Python: `xcode-select --install`（`/usr/bin/python3` が入る）、または `brew install python`
- Node.js: `brew install node`、または [nvm](https://github.com/nvm-sh/nvm) で導入

```sh
brew install node
```

macOS では Python を `python3`、Node を `npm` で起動します。Scoop の PATH 追記は不要です。

### 3.3 フロントの依存（全 OS 共通）

初回のみ、フロントの依存をインストールします。

```sh
cd webapp
npm install
```

---

## 4. 起動方法

API とフロントを**別々のターミナル**で起動します。

### 4.1 ターミナル A: API サーバ

リポジトリのルートで実行します（起動したままにする）。

Windows:

```powershell
python webapp/server/server.py --port 8000
```

macOS:

```sh
python3 webapp/server/server.py --port 8000
```

`RangeCalc API listening on http://127.0.0.1:8000` と表示されれば起動成功です。
ポートを変えたい場合は `--port` を変更し、`vite.config.ts` の `proxy.target` も合わせて
ください。

### 4.2 ターミナル B: フロントエンド

コマンドは Windows / macOS 共通です。

```sh
cd webapp
npm run dev
```

バナーが次のように表示されれば起動成功です（`127.0.0.1` 固定）。

```text
  ➜  Local:   http://127.0.0.1:5173/
```

ブラウザで **http://127.0.0.1:5173/** を開きます。
`localhost` ではなく `127.0.0.1` を使うのが確実です。

### 4.3 停止

各ターミナルで `Ctrl+C` を押します。プロセスが残ってしまった場合は次で掃除します。

Windows:

```powershell
Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
```

macOS:

```sh
pkill -f "vite" || true
pkill -f "server/server.py" || true
```

---

## 5. 操作方法

1. 上部タブで **弾道** または **軌道** を選ぶ。弾道タブでは **初速** と **発射角**、
   必要に応じて **スピン回転数** / **スピン軸角** と **表示**（断面 / 上面）を調整する
   （抗力係数 Cd は球体の既定値 0.47 に固定）。
2. 軌道タブでは **重力モデル**（ニュートン / ニュートン+J2）を選び、**軌道半径 r** と
   **軌道速度 v**（既定は円軌道速度を自動設定）を調整する。
3. **抗力（密度）モデル** を選ぶ（なし / 一様 / 指数 / 区分指数）。軌道では「なし」を推奨。
4. 必要に応じて **刻み幅 dt** を変更、または **adaptive** を有効にする。
5. 「**シミュレーション実行**」を押す。実行時に前回の Result と軌跡はクリアされ、
   計算中は `計算中...` を表示する。
6. 結果が得られると **Result** にメトリクス（弾道 / 軌道で自動切替）、下段 **Trajectory**
   に軌跡チャートが表示される。
7. 条件を変えて再実行すると結果が更新される。初回表示時にも既定値で1回実行されます。
8. エラー時は Result を表示せず、日本語のエラーメッセージを表示する。

`adaptive` は刻みを安定性上限内に**短縮**する発散防止機構であり、精度向上を保証する
ものではありません（詳細は `range_calculator/SPEC.md` 第3章）。

---

## 6. 開発コマンド

`webapp` ディレクトリで実行します。

| コマンド | 内容 |
|----------|------|
| `npm run dev` | 開発サーバ起動（http://127.0.0.1:5173/） |
| `npm run build` | 型チェック（`tsc -b`）＋本番ビルド（`dist/` 生成） |
| `npm run preview` | ビルド成果物のプレビュー（API 連携には別途サーバが必要） |
| `npm run lint` | oxlint による静的解析 |

### 6.1 テスト

バックエンドが使う物理コアは既存のテストで検証されています（Windows は `python`、
macOS は `python3`）。次のコマンドは `webapp` ではなく**リポジトリのルート**で
実行します。

```sh
python3 -m unittest discover -s range_calculator -p "test_*.py"
python3 tools/check_text_hygiene.py
```

API 層（`simulate` の重力モデル切替・軌道要素出力）は `webapp/server/test_server.py` で
検証します。`webapp/server/` で実行してください（`server` の import 時に
`range_calculator` がパスに追加されます）。

```sh
python3 -m unittest test_server
```

---

## 7. トラブルシューティング

| 症状 | 原因 / 対処 |
|------|-------------|
| ブラウザで `ERR_CONNECTION_REFUSED`（ページ自体） | dev サーバが IPv6 (`::1`) のみで待ち受けている。`vite.config.ts` は `host: '127.0.0.1'` 済み。`npm run dev` を**再起動**し、バナーが `127.0.0.1` になっているか確認 |
| `http proxy error: /api/... ECONNREFUSED 127.0.0.1:8000` | API サーバが未起動。ターミナル A で API を起動（Windows: `python webapp/server/server.py --port 8000` / macOS: `python3 ...`） |
| `Port 5173 is in use` | 古い Vite が残存。Windows: `Get-Process node \| Stop-Process -Force` / macOS: `pkill -f vite` |
| `node` / `npm` が見つからない | Scoop 導入後にシェルを開き直す。または §3.1 の PATH 追記を実行（macOS は `brew install node`） |
| `python: command not found`（macOS） | macOS では `python3` を使う |
| 画面に `エラー: ...` が出る | 入力値不正、または API 側の検証（刻み幅が粗すぎる等）に失敗。日本語メッセージの内容に従い入力を修正する |

---

## 8. 関連ドキュメント

- 物理モデル・テスト仕様: `range_calculator/SPEC.md`
- 環境構築（macOS / 共通）: `docs/setup-machine.md`
- 環境構築（Windows 11）: `docs/setup-windows.md`
