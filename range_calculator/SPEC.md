# 物理モデル仕様書 — 弾道シミュレーション（range_calc v4/v5）

対象コード: `range_calc.py` / `ballistics.py` / `physics_config.py`

本仕様書は v4（固定刻み）を基礎とし、v5 では任意モードとして適応刻み（`adaptive=True`）を追加する。v4・v5 時点の CLI は `range_calc_v4.py` という名称だったが、その後 `range_calc.py` に改称されており、現行リポジトリにはこの名称で存在する。

---

## 1. 目的と適用範囲

本仕様書は、本ツールが解く方程式・使用する物理定数・数値解法・その**適用限界**を定義する。
コードの改変時には、この文書を根拠とした変更レビューを行うこと。

本ツールが扱う問題は次の1つに厳密に限定される。

> 等質で球形の弾丸を、**大気が静止した地球上で**水平面に対して角度 θ（発射角）で初速度 `v0` で発射したとき、
> **速度の2乗に比例する空気抵抗（抗力）のみを考慮して**地面衝突までの距離と飛行時間を求める。

したがって本ツールは **到達距離の相対比較と傾向分析**のためのツールであり、
実測弾道データとの絶対一致や競技規則的精度を要求する用途には用いない（理由は第7章）。

---

## 2. モデルの基礎方程式

### 2.1 状態ベクトル

| 記号 | 意味 | 単位 |
|------|------|------|
| `x` | 水平位置（射程方向） | m |
| `y` | 射出点からの鉛直高さ | m |
| `z` | 水平位置（横方向。スピン時のみ非零） | m |
| `vx` | 水平速度成分（射程方向） | m/s |
| `vy` | 鉛直速度成分 | m/s |
| `vz` | 水平速度成分（横方向。スピン時のみ非零） | m/s |

状態は 6 元組 `State = (x, y, z, vx, vy, vz)` として保持される。
モジュール定数 `X, Y, Z, VX, VY, VZ` が各成分のインデックスを与える。
単位系は内部で **SI 一貫（m, s, kg）** に統一されている（温度は使用しない）。

### 2.2 作用する力

自由飛行に対応する2つの力のみをモデル化する。

**(a) 重力** — 既定モデルでは座標系の鉛直下向き `-y` 方向に、質量によらず一定の加速度を与える。

```
ay = -g        g = 9.81 m/s^2
```

（`gravity` パラメータで変更可能。既定の平面弾道モデルは球面・緯度依存を考慮しない。→ 第7章）

重力は加速度場 `gravity(state) -> (ax, ay, az)` として差し替え可能である
（内部表現: `GravityModel`、積分は `derivatives_with_gravity()`）。既定モデル `constant_gravity()`
は上記の一定加速度を返す。もう一つの実装 `newtonian_gravity(mu)` は原点へ向かう逆二乗則

```
a = -mu · r / |r|³        r = (x, y, z),  mu = 中心天体の G·M
```

を与え、位置の原点を中心天体の中心とする軌道計算に用いる。軌道計算では地面衝突判定
（`ground_collision=False`）と `from_state()` による全状態指定を使う。標準重力パラメータは
`mu` パラメータ（既定: 地球の 3.986004418e14 m³/s²）で与える。

**J2 扁平摂動** — `j2_gravity(mu, j2, equatorial_radius)` は上記の点質量項に第2帯球関数
（扁平）項を加えた場を返す。極軸は座標 `z` 軸とし、`s = z/|r|` として

```
a_J2 = -(3/2) · J2 · mu · R² / |r|⁵ · ( (1-5s²)x, (1-5s²)y, (3-5s²)z )
```

`J2` は `J2_EARTH = 1.08263e-3`、`R`（`equatorial_radius`）は地球赤道半径 6.378137e6 m を既定
とする。`j2 = 0` のとき場は厳密に `newtonian_gravity(mu)` と一致する（摂動は完全に任意）。

**多体合成** — `sum_fields(*fields)` は任意個の加速度場を成分ごとに加算した場を返す。各中心天体を
独立の `mu`/`j2` 場として与えれば多体問題へ拡張できる（合成フックであり、既定は単体のまま）。

**(b) 空気抵抗（抗力）** — 速度ベクトルの**逆方向**に大きさが速度の2乗に比例する力。

```
a_drag = -k · v · |v|          既に質量で割った加速度形式（実装が使う形）

k = (1/2 · ρ · A · Cd) / m     単位: m⁻¹
```

| 記号 | 意味 | 既定値 |
|------|------|--------|
| `ρ` (`air_density`) | 空気密度 | 1.225 kg/m³ |
| `A` (`frontal_area`) | 正面投影面積（円形） | π (d/2)² |
| `d` (`diameter`) | 弾丸直径 | 0.075 m |
| `Cd` (`drag_coefficient`) | 抗力係数 | 0.47 |
| `m` (`mass`) | 弾丸質量 | 0.149 kg |

`k` は以下のように算出される（`PhysicalParameters.drag_scaling_factor()`）。

```
A    = π (0.075 / 2)²           = 4.417865e-03 m²
k    = 0.5 × 1.225 × 4.417865e-03 × 0.47 / 0.149
                                 = 8.535522e-03  m⁻¹
1/k  = 117.16 m                 （弾道係数 m / (0.5 ρ Cd A) の逆数）
```

`k` は物理定数の導出値であり、実行時に直接指定しない。
レガシー互換のため `{"drag_scaling_factor": k}` を渡すと `Cd` を逆算して上書きする
（`PhysicalParameters.with_drag_scaling_factor()`）。

**高度依存の抗力（大気モデル）** — 抗力も加速度場 `drag(state) -> (ax, ay, az)`
（内部表現: `DragModel`）として差し替え可能である。既定の `constant_drag(k)` は上記の
一定密度抗力に一致する。軌道計算用に、密度を高度の関数とする

```
DensityModel = Callable[[float], float]        a_drag = -k(h) · v · |v|
k(h) = (1/2 · ρ(h) · A · Cd) / m
```

を用意する。密度モデルは次の3種:

| 関数 | 定義 |
|------|------|
| `constant_density(rho)` | `ρ(h) = rho`（高度に依存しない） |
| `exponential_density(rho0, H, h0=0)` | `ρ(h) = rho0 · exp(-(h-h0)/H)`（単一スケールハイト近似） |
| `tabulated_density(layers)` | `(基準高度, rho, H)` 層テーブルによる区分指数近似 |

`atmospheric_drag(parameters, density_model, altitude)` は `altitude(state)` で得た高度から
`k(h)` を評価し、`derivatives_with_models()` 経由で積分に渡される。既定の層テーブル
`EARTH_ATMOSPHERE_LAYERS` は 0–1000 km の区分指数フィット（基準密度・スケールハイトは
`scale_height` / `sea_level_density` とは独立の代表値）である。高度の取り方には
`orbital_altitude(R) = |r| - R`（球面）と `flat_altitude() = y`（平面）がある。

### 2.3 時間発展方程式（微分方程式）

```
dx/dt  = vx
dy/dt  = vy
dz/dt  = vz
dvx/dt = -k · vx · |v|
dvy/dt = -k · vy · |v| - g
dvz/dt = -k · vz · |v|

|v| = sqrt(vx² + vy² + vz²)
```

この6元の1階連立ODEを数値的に解く（`ballistics.derivatives()`）。横方向 `z` / `vz` は
`dvz/dt` が抗力のみでは零であり、Magnus 揚力を有効にしたときに初めて駆動される（§7 item 5）。

### 2.4 軌道要素（`orbital.py`）

ニュートン重力での軌道は、位置 `r`・速度 `v` と中心天体の `mu` から
**軌道要素**（`OrbitalElements`、`orbital_elements(state, mu)`）として解析的に表せる。

| 要素 | 定義 |
|------|------|
| `specific_energy` | 比エネルギー `ε = |v|²/2 − μ/|r|` |
| `semi_major_axis` | 長半径 `a = −μ/(2ε)`（放物線 `ε = 0` では `None`） |
| `eccentricity` | 離心率 `e = |e_vec|`、`e_vec = ((|v|² − μ/|r|) r − (r·v) v)/μ` |
| `periapsis` | 近点半径 `r_p = h²/(μ(1+e))`、`h = |r × v|` |
| `apoapsis` | 遠点半径 `a(1+e)`（開軌道 `e ≥ 1` では `None`） |
| `period` | 公転周期 `T = 2π√(a³/μ)`（開軌道では `None`） |
| `inclination_rad` | 軌道傾斜角 `acos(h_z/h)` |

`|r| = 0`（中心天体上）や `mu ≤ 0` は定義できないため `ValueError` を送出する。
円軌道（`e ≈ 0`）では `r_p ≈ r_a ≈ a` となる。

---

## 3. 初期条件と単位変換

| 項目 | 定義元（優先順） | 既定値 |
|------|------------------|--------|
| 発射速度 | `--v0=<km/h>` → `data.csv` 第1フィールド | 170.0 km/h |
| 発射角 | `--angle=<deg>` → `data.csv` 第2フィールド | 35.0 ° |
| 射出点 | `LAUNCH_X`, `LAUNCH_Y` | (0.0, 0.0) |

発射速度と発射角は**フィールド単位で独立に**解決される（`load_scenario()`）。
CLI オプションで与えられた項目はファイルを読まずに採用され、未指定の項目は
`data.csv`、そこからも読めない場合は既定値に落ちる。
両オプションを指定した場合は `data.csv` を一切読まない（欠損警告も発しない）。

```
v0_mps = velocity_kmph × 1000 / 3600          (170.0 km/h → 47.2222 m/s)
θ_rad  = radians(angle_deg)
vx0    = v0 · cos θ
vy0    = v0 · sin θ
```

初速 `v0` と発射角 `θ` は正の値を前提とする（負角・下向き発射は非対応。
負角を入力した場合は `launched_upwards` が偽となり、起動直後の着弾検出が
1ステップ目のガードに掛からない点に注意）。
データファイル `data.csv` は `velocity_kmph, angle_deg` の1行 CSV 形式。

---

## 4. 数値解法

### 4.1 積分手法：古典的4次ルンゲ–クッタ（RK4）

解法には**古典的陽的4次ルンゲ–クッタ法（RK4）** を採用する。

2つの動作モードが存在する：

- **固定刻みモード（`adaptive=False`）**: 刻み幅 `dt` は固定で、各ステップは `state → next_state` の陽的な写像として計算される（実装: `ballistics.ProjectileSimulator._rk4_step()`）。
- **適応刻みモード（`adaptive=True`、v5 で追加）**: 刻み幅の上限を `dt_max` とし、各ステップでは `h = min(dt_max, STABILITY_LIMIT / (k · |v_now|))` として**必要なときのみ短縮**する。縮小のみで延長は行わない（実装: `ballistics.ProjectileSimulator._next_timestep()`）。

既定刻み幅/上限は `dt = 0.01 s`。局所打ち切り誤差は `O(dt⁵)`、全体では `O(dt⁴)`。
`max_time = 300 s` 上限まで飛行した場合の計算コストは最大 30,000 ステップ／回（固定刻み時）。

### 4.2 安定性条件

陽的RK4の線形安定域の限界（無次元量 `z = dt·k·v`）から、以下を**安定性上限**とする。

```
dt_max = STABILITY_LIMIT / (k · v)          STABILITY_LIMIT = 0.5
```

初期条件での参考値（`k=8.535522e-03`, `v0=47.2222`）では

```
dt_max ≈ 1.2405 s
```

`dt > dt_max` の場合（固定刻みモード）、`run_simulation()` は `RuntimeWarning` を発して続行するが、
**この警告は発散防止に過ぎず、精度の保証ではない**。適応刻みモードでは `dt_max` を超えないように自動的に短縮する。
実測の到達距離誤差は概ね `(dt · k · v)²` に比例して増大するため、精度を確保するには `dt_max` より十分小さい
値（既定の 0.01 s は `dt_max` の約 1/124 で、十分に安全側にある）が望ましい。
適応刻みは発散を防ぐための機構であり、刻みを上限いっぱいまで拡大した場合の精度を保証するものではない点に注意する。

### 4.3 地面衝突（`y = 0`）の扱い

各ステップ後に `y < 0` になった場合、そのステップ内の `y = 0` 交点を**線形補間**で求め、
衝突時の状態 `(x, y=0, z, vx, vy, vz)` を確定する（`_interpolate_ground_crossing()`）。
交点時刻は `t + ratio · dt`。補間比率 `ratio` は [0,1] にクランプされる。
`y` ちょうど 0 となる退化ケース（`span = 0`）では `ratio = 1.0` を採用する。

---

## 5. 打ち切り条件と数値ガード

| 条件 | 閾値 | 挙動 |
|------|------|------|
| 時間上限 | `max_time = 300 s` | `timed_out = True` で停止、警告表示 |
| 発散（非有限値） | 状態成分に `NaN`/`Inf` | `SimulationDiverged` を送出 |
| 発散（速度異常） | `max(v0 × 1000, g × max_time)` 超 | `SimulationDiverged` を送出 |
| 粗すぎる刻み | 第1ステップで上昇中発射が地面到達 | `ValueError` を送出 |

- `divergence_speed_factor = 1000.0`（倍率）は `ProjectileSimulator` のキーワード引数で上書き可。
- 物理的な「着弾後の跳ね返り」は計算しない。1回の地表面交差で終了する。
- `reset()` は初期状態・時刻・フラグ・ステップ数をすべて初期化する。`resume=True` で中断点から継続可能（着弾済みの場合は no-op）。
- `FlightResult.landed` は地面に到達した場合に `True`。
- `reset()` を呼び出すと、射出条件・時刻・フラグ・ステップ幅がすべて初期状態に戻る。

---

## 6. パラメータの外部定義

物理定数は `config/physics_constants.json` から読み込む（`physics_config.load_parameters()`）。

```json
{
  "max_time": 300.0,
  "gravity": 9.81,
  "air_density": 1.225,
  "mass": 0.149,
  "diameter": 0.075,
  "drag_coefficient": 0.47,
  "mu": 3.986004418e14,
  "j2": 0.00108263,
  "equatorial_radius": 6378137.0,
  "scale_height": 8500.0,
  "sea_level_density": 1.225
}
```

| JSON キー | 内部フィールド | 単位 | 制約 |
|-----------|---------------|------|------|
| `max_time` | `max_time` | s | `> 0` |
| `gravity` | `gravity` | m/s² | `> 0` |
| `air_density` | `air_density` | kg/m³ | `≥ 0` |
| `mass` | `mass` | kg | `> 0` |
| `diameter` | `diameter` | m | `> 0` |
| `drag_coefficient` | `drag_coefficient` | — | `≥ 0` |
| `mu` | `mu` | m³/s² | `> 0` |
| `j2` | `j2` | — | `≥ 0` |
| `equatorial_radius` | `equatorial_radius` | m | `> 0` |
| `scale_height` | `scale_height` | m | `> 0` |
| `sea_level_density` | `sea_level_density` | kg/m³ | `≥ 0` |

`mu` は中心天体の標準重力パラメータ G·M であり、球面重力モデル
（`ballistics.newtonian_gravity()`）でのみ使う。既定の平面弾道モデルは `gravity` を使い、
`mu` は参照しない。`j2` / `equatorial_radius` は `j2_gravity()` の摂動項、
`scale_height` / `sea_level_density` は `exponential_density()` の単一指数大気に使う。
いずれも既定モデル（一定重力・一定密度抗力）では参照しない。

制約違反は dataclass の `__post_init__` で検証され、`TypeError` / `ValueError` を送出する。
未知のキーは `ValueError`（strict な検証）。JSON の構文エラーも `ValueError` に変換される。
**設定ファイルが不在の場合は警告とともに組み込み既定値へ退避する**（設定と独立に動作する）。

---

## 7. モデルの適用限界（明示的に無視する物理効果）

以下は本ツールが**意図的に考慮していない**項目であり、結果の解釈範囲を限定する。

1. **高度依存の大気密度** — 既定モデルは `ρ` を一定（1.225）とするため、高打球では実際より
   抗力を過大評価する。区分指数大気モデル（`tabulated_density()` / `exponential_density()`）へ
   切り替えれば高度依存は扱えるが、層テーブルは代表値であり、温度・太陽活動依存は考慮しない。
2. **重力の実高度・緯度依存** — 既定モデルは `g` を 9.81 一定とする（実際の上昇では約1%減衰）。
   球面重力モデル（`newtonian_gravity()`）へ切り替えれば高度依存（逆二乗則）は扱える。
   さらに `j2_gravity()` で扁平（帯球）項を加えられるが、緯度依存の高次項・遠心力は考慮しない。
3. **地形の曲率（地球の球面性）** — 平面 x-y 座標を用いる。本ツールの基準ケースでは
   射程 101 m であり、地球の曲率による高低差は最大約 0.8 mm（0.0008 %）に留まるため
   影響は実用的に無視できる。射程が 10 km 規模に達すると高低差は約 8 m となり、
   誤差が顕在化する。
4. **風・突風・空気の移流** — 大気静止を仮定。
5. **回転による揚力（Magnus効果）・スピンの軌道への影響** — 既定では無視（スピン 0）。
   ただし任意で簡易 Magnus 揚力モデルを有効化できる（`spin_rate` / `spin_axis`）。
   揚力係数は `C_L = min(slope · S, max)`（`S = |ω| R / v`、`R = 直径/2`、
   `ω = spin_rate · 2π/60`、既定 `slope = 1.0` / `max = 0.3`）、加速度は
   `a = (1/2 · ρ · A · C_L / m) · v · (ŝ × v)` で、回転軸 `ŝ` は `spin_axis` で張る。
   実測の回転球空力に基づく厳密モデルではなく、定性的な左右・上下のずれを与える
   近似である（CLI は §9 の `--spin` / `--spin-axis`）。
6. **反発係数・跳ね返り** — 初衝突で計算終了。
7. **温度・湿度による `Cd` と `ρ` の変動** — 固定値とする。
8. **形状による抗力係数の変動** — `Cd = 0.47` を定数とする（球体近傍の代表値）。
9. **`Cd = 0.47` と球径・質量の整合性** — 質量 149 g / 直径 75 mm は野球ボール相当だが、
   野球ボールの実測 `Cd` は自由飛行でおおむね 0.33–0.36、風洞実験では球種により 0.3 前後
   まで低下する（例: NPB）。本値は直径75 mm・平滑な球に
   対する実験値であり、**どの球種を想定した値かを定量的な出典で
   確認するまで、本値は暫定値として扱う**。
   既定プロファイルの質量 149 g・直径 75 mm は野球ボールの公認寸法（質量 141.7–148.8 g、
   円周 22.9–23.5 cm）に基づく値であり、`Cd = 0.47` はこのサイズ・質量の球体に対する
   代表値である。球種を限定した実測値（MLB 自由飛行: 0.348/0.358、NPB 風洞: MLB より低値）
   は回転・風洞条件に依存するため本ツールでは採らず、**`Cd = 0.47`（球体代表値）に固定**
   する。Web アプリ（`webapp/README.md`）・デスクトップ GUI とも `drag_coefficient` は
   この既定値を送信し、UI に球種プリセットの選択は設けない。
10. **縮尺効果（直径依存 Reynolds 数）** — 高速域での `Cd` 変化は考慮しない。

---

## 8. 検証基準

### 8.1 解の正当性（解析解との整合）

無抗力（真空）の理想射程には解析的な閉形式が存在するため、数値解と直接比較できる。

```
R_ideal = v0² · sin(2θ) / g
```

`v0 = 47.2222 m/s`, `θ = 35°`, `g = 9.81` のとき

```
R_ideal = 213.60 m
```

`ProjectileSimulator.calculate_ideal_range()` はこの値を返す。

### 8.2 参照ケース（基準シナリオ）

現行コードから観測された基準値（`data.csv = 170, 35`, `dt = 0.01 s`）。

| 指標 | 参照値 |
|------|--------|
| 初速 | 47.2222 m/s (170 km/h) |
| 発射角 | 35.0 ° |
| 理想射程（無抗力） | 213.60 m |
| 実射程（抗力あり RK4） | 101.12 m |
| 飛行時間 | 4.37 s |
| 抗力による到達距離の低減率 | 約 52.7 % |
| 無次元抗力パラメータ `k·v0²/g` | 1.94 |
| 統合ステップ数（固定刻み, `dt=0.01`） | 438 |

`k·v0²/g` は抗力加速度と重力加速度の初速時における比であり、これが 1 を超える場合は
飛行の初期段階で抗力が重力を上回る。本ケースでは 1.94 であり、抗力の影響は無視できない領域にある。
`k·v0²/g ≫ 1` では `R_ideal` からの乖離が指数的に増大するため、無抗力解を近似として用いてはならない。

### 8.3 テストによる検証

`test_range_calc.py` に以下の10系統・全58件のテストが存在する。テストはフラット
import（`import ballistics` 等）を用いるため、カレントディレクトリに注意すること
（リポジトリルートまたは `range_calculator/` のどちらからでも実行できる）:

```text
python3 -m unittest discover -s range_calculator -p "test_*.py"   # リポジトリルートから
python3 -m unittest test_range_calc                               # range_calculator/ から
```

Windows では `python3` の代わりに `python` でもよい（Scoop 構成では `python` と
`python3` の両方が有効。`py` は解決されない）。

| クラス | 検証対象 |
|--------|----------|
| `AnalyticAgreementTests` | `k = 0` で射程・飛行時間が閉形式と一致すること（`delta = 1e-4`） |
| `ConvergenceTests` | 着弾補間により `dt = 0.01` と `dt = 0.0001` で結果が一致すること |
| `LandingStateTests` | 着弾状態（`y = 0`、下降中、水平発射で原着弾）の妥当性 |
| `PhysicsTests` | 抗力による射程短縮、最適角度が 45° 未満になること |
| `RegressionTests` | 基準シナリオの射程 101.12 m・飛行時間 4.37 s に一致すること |
| `SimulatorContractTests` | `reset()` / `resume` の契約整合・冪等性、引数検証、コアモジュールの I/O 禁止 |
| `ConfigurationTests` | パラメータ読み込み・検証・未知キー・レガシー互換 |
| `ScenarioLoadingTests` | `data.csv` 欠損・不正時の既定値退避、CLI 実行 |
| `NumericalGuardTests` | 発散検出、粗すぎる刻みの警告・例外 |
| `MagnusLiftTests` | スピン軸ベクトル、Magnus 揚力による横ずれ `z`、回転数 0 での無効化 |

v5 では `test_adaptive_timestep.py`（39件）と `test_orbital.py`（36件、ニュートン/J2 重力場・
円/楕円軌道・`orbital_elements()`・密度/抗力モデル）が追加され、`range_calculator` 全体で
133 件となる。適応刻みモード（`adaptive=True`）は、安定性帯内では固定刻みと一致し、安定性帯を
超える `dt_max` でも発散せず完走するが、精度改善を保証しない点がこれらのテストで固定されている。

---

## 9. CLI 仕様（v5）

```text
python range_calc.py [scenario_path] [dt_max] [--adaptive] [--v0=<km/h>] [--angle=<deg>]
python range_calc.py --spin=<rpm> [--spin-axis=<deg>] [--v0=<km/h>] [--angle=<deg>]
python range_calc.py --orbital [--radius=<m>] [--v0=<km/h>] [--adaptive] [--j2] [--atmosphere]
```

- `scenario_path`: `data.csv` のパス（省略可）。指定しない場合は同ディレクトリの `data.csv` を読み込む。
- `dt_max`: タイムステップの上限値（秒）。省略した場合は `0.01` s。
- `--adaptive`: 指定すると適応刻みモードを有効にする。省略した場合は固定刻みモードとなり、**挙動は v4 と完全に同一**である。
- `--v0=<km/h>`: 初速の上書き（単位 km/h）。**`=` 書式のみ受理**（`--v0 160` はエラー）。省略時は第3章の定義元に従う。
- `--angle=<deg>`: 発射角の上書き（単位 °）。書式・省略時の挙動は `--v0` と同じ。
  両オプションともフィールド単位で独立にフォールバックし（引数 → CSV → 既定値）、
  両方指定した場合は `data.csv` を読まない。不正値・`=` なし・重複指定は `SystemExit` で拒否される。
- `--orbital`: 地表弾道の代わりに中心重力場の軌道を積分する。初期状態は +x 軸上の
  `--radius` に置かれ、初速は軌道接線方向（`--angle` は無視）となる。`ground_collision=False`
  で実行され、実行後に軌道要素（`orbital_elements()`）を出力する。摂動フラグを付けない場合は
  抗力無効・`newtonian_gravity(mu)`（閉軌道）となる。
- `--radius=<m>`: 軌道モードの初期半径（単位 m）。既定値 `7.0e6` m。`0` 以下は `SystemExit` で拒否される。
- `--j2`: 軌道モードの重力を `j2_gravity(mu, j2, equatorial_radius)`（扁平摂動つき）にする。
- `--atmosphere`: 軌道モードの抗力に区分指数大気（`tabulated_density(EARTH_ATMOSPHERE_LAYERS)`）を
  有効にする。省略時は抗力無効（`drag_coefficient = 0`）で、`--j2` と独立に指定できる。
- `--spin=<rpm>`: 弾道に Magnus 揚力を加える（§7 item 5）。`0` 以外を指定すると
  `magnus_lift(DEFAULT_PARAMETERS, spin, axis)` が有効になり、出力に `Spin Rate` /
  `Spin Axis Angle` と横ずれ `Lateral Drift` が加わる。
- `--spin-axis=<deg>`: 回転軸を下流軸まわりに傾ける角度（deg）。`0` でバックスピン、
  `+90` で *+z*、`-90` で *-z*、`±180` でトップスピン。省略時は `0`。`--spin` と併用する。

`parse_args()` は `CliArgs(path, dt_max, adaptive, v0_kmph, angle_deg, spin_rpm, spin_axis_deg, orbital, radius, j2, atmosphere)`
を返す（`spin_rpm` / `spin_axis_deg` は既定 `0.0`、`j2` と `atmosphere` は既定 `False`）。

適応刻みモードでは、各ステップの刻み幅 `h` は `dt_max` を超えない範囲で安定性上限内に短縮される（縮小のみ）。`FlightResult` には `steps` / `timestep_min` / `timestep_max` が含まれ、CLI 出力には `Integration Steps` および `Shortest Step Taken`（`timestep_min < dt_max` の場合）が表示される。

---

## 10. 変更管理

物理定数・方程式を変更する場合、以下を遵守すること。

1. `physics_config.py` の `PhysicalParameters` にフィールドを追加する場合は、
   `PositiveFields` / `NonNegativeFields` の制約分類を必ず定義すること。
2. `config/physics_constants.json` に手を加えた場合は、8.2 節の参照値を再計測して
   併せて更新すること。
3. 方程式（`derivatives()`）を変更した場合は、`k = 0` で閉形式に一致し続けることが
   必須である（`AnalyticAgreementTests` がこれを保証する）。
4. 第7章に新しく「無視する物理効果」を追加した場合、その項目を本書に追記すること。

---

## 11. 開発環境と検証手順

- **Python**: 3.9 以上（標準ライブラリのみで動作する）。macOS / Windows 11 の
  Python 3.15 で検証している。Windows は Scoop 構成であり、`python` / `python3` で
  起動できる（`py` は解決されない。詳細は `docs/setup-windows.md` を参照）。
- **Node.js（`webapp` を使う場合のみ）**: 20.19 以上 / 22.12 以上（Vite 8 の要件）と
  npm。起動・ビルドは `webapp/README.md` を参照。物理コアのみを使う場合は不要。
- **デスクトップ GUI（`desktop` を使う場合のみ）**: 標準ライブラリの Tkinter のみで
  動作し、追加の `pip` パッケージは不要（実行ファイル化のビルド時のみ PyInstaller
  を使用）。起動・ビルドは `desktop/README.md` を参照。
- **テスト**: 8.3 節のコマンドを実行し、133 件すべてがパスすることを確認する。
  `desktop` のテストは `python3 -m unittest discover -s desktop/tests -p "test_*.py"`
  で実行する（`webapp` との対応漏れ検出を含む。`desktop/PLAN.md` §9 を参照）。
- **文字混入検査**: `python3 tools/check_text_hygiene.py`（`0 finding(s)` が正常）。
- **pre-commit フック**: クローンごとに一度だけ次を実行する（`docs/setup-machine.md` /
  `docs/setup-windows.md` と共通）。

  ```sh
  bash tools/bootstrap.sh .
  ```

  これは `git config core.hooksPath .githooks` を含む。以降、コミット時に
  `tools/check_text_hygiene.py` が自動実行され、混入文字が 1 件でもあればコミットが
  拒否される（フック本体は `.githooks/pre-commit`、Windows のセットアップ手順は
  `docs/setup-windows.md` を参照）。

---

*最終更新: 摂動モデル（J2 扁平 `j2_gravity()`・合成 `sum_fields()`）と高度依存抗力
（`DensityModel` / `DragModel`、区分指数大気）を §2.2/§6/§7/§9 に追記し、テスト数を 133 に
更新した（2026-10-17）。前回は第11章にデスクトップ GUI（`desktop/`、Tkinter）の実行時依存が
標準ライブラリのみである旨と、そのテストコマンドを追記した（2026-10-10）。*
