# 物理モデル仕様書 — 弾道・軌道・多体シミュレーション（range_calculator）

対象コード: `range_calc.py` / `ballistics.py` / `physics_config.py` / `orbital.py` / `nbody.py`

本仕様書は v4（固定刻み）を基礎とし、v5 では任意モードとして適応刻み（`adaptive=True`）を
追加する。v4・v5 時点の CLI は `range_calc_v4.py` という名称だったが、その後 `range_calc.py`
に改称されており、現行リポジトリにはこの名称で存在する。v5 以降は版番号を振らず、軌道
（`orbital.py`・J2 扁平・高度依存大気）と多体（`nbody.py`）へ対象を拡張した（履歴は `HISTORY.md`）。

本書は **4 部構成**である。第I部は 3 モデルが共有する基盤を、第II部〜第IV部は各モデル固有の
問題設定・方程式・初期条件・検証基準・適用限界・CLI を定義する。コードを改変する際は、
変更に最も近い部の章を根拠としてレビューすること。

| 部 | モデル | 主なモジュール | 章 |
|----|--------|----------------|----|
| 第I部 共通基盤 | （3 モデル共有） | — | 1–7 |
| 第II部 弾道 | 地表からの弾丸の飛行 | `ballistics` / `range_calc` | 8–15 |
| 第III部 軌道 | 中心天体まわりの 2 体軌道 | `orbital` / `ballistics` の重力・抗力モデル | 16–23 |
| 第IV部 多体 | 複数天体の相互重力 | `nbody` | 24–31 |

---

## 第I部 共通基盤

3 モデルは同じ 6 元状態ベクトル、同じ陽的 4 次ルンゲ–クッタ（RK4）、同じ外部定数ファイルを
共有する。ここではモデルに依存しない契約を定義する。

### 1. 目的と適用範囲

本仕様書は、各モデルが解く方程式・使用する物理定数・数値解法・その**適用限界**を定義する。
コードの改変時には、この文書を根拠とした変更レビューを行うこと。

本ツールが扱う問題は次の 3 モデルである。

> **弾道**（第8章〜第15章）— 等質で球形の弾丸を、**大気が静止した地球上で**水平面に対して
> 角度 θ（発射角）で初速度 `v0` で発射したとき、**速度の 2 乗に比例する空気抵抗（抗力）**を
> 考慮して地面衝突までの距離と飛行時間を求める。任意でスピンによる Magnus 揚力を加える
> （第9章 (c)）。
>
> **軌道**（第16章〜第23章）— 中心天体を原点とする座標系で、点質量重力（ニュートン）と
> 第 2 帯球（J2）扁平摂動、および高度依存大気のもとで軌道を積分し、その状態を**軌道要素**
> （長半径・離心率・傾斜角など）へ換算する（第19章）。
>
> **多体（N 体）**（第24章〜第31章）— 複数天体の相互重力（点質量）を完全 N 体として積分する。
> どの天体も固定された中心に繋がれず、互いに自由落ちる。

いずれのモデルも、加速度場の合成と陽的 4 次ルンゲ–クッタ（RK4）で解く（第3章）。
追加の順は `HISTORY.md` を参照。

したがって本ツールは **物理挙動の相対比較と傾向分析**のためのツールであり、実測データとの
絶対一致や競技規則的精度を要求する用途には用いない（理由は各モデルの適用限界:
第14章・第22章・第30章）。

### 2. 状態ベクトルと単位系

すべてのモデルが 6 元の状態ベクトルを単位とする。

| 記号 | 意味 | 単位 |
|------|------|------|
| `x` | 位置成分 | m |
| `y` | 位置成分 | m |
| `z` | 位置成分 | m |
| `vx` | 速度成分 | m/s |
| `vy` | 速度成分 | m/s |
| `vz` | 速度成分 | m/s |

状態は位置と速度の 6 成分 `State = (x, y, z, vx, vy, vz)` として保持される。
モジュール定数 `X, Y, Z, VX, VY, VZ` が各成分のインデックスを与える。
単位系は内部で **SI 一貫（m, s, kg）** に統一されている（温度は使用しない）。

同じ 6 成分を、モデルごとに異なる座標系で解釈する。

| モデル | 原点 | 座標の意味 | 状態の形 |
|--------|------|-----------|----------|
| 弾道 | 射出点（`LAUNCH_X`, `LAUNCH_Y`, `LAUNCH_Z`。既定 `(0,0,0)`） | `x` = 射程方向、`y` = 鉛直高さ（地面は `y = 0`）、`z` = 横方向 | 単一の `State` |
| 軌道 | 中心天体の中心 | `r = (x, y, z)` は中心からのオフセット | 単一の `State` |
| 多体 | （系全体の仮想の原点） | 各天体が自前の位置と速度の 6 成分を持つ | `tuple[State, ...]`（計 6N 成分） |

弾道と異なり軌道・多体には「地面」が存在しない。軌道では `ground_collision=False` を指定して
地面交差判定を無効化する（第20章）。

### 3. 数値解法

#### 3.1 積分手法：古典的 4 次ルンゲ–クッタ（RK4）

解法には**古典的陽的 4 次ルンゲ–クッタ法（RK4）**を採用する。
局所打ち切り誤差は `O(dt⁵)`、全体では `O(dt⁴)`。

2 つの動作モードが存在する。

- **固定刻みモード（`adaptive=False`、既定）**: 刻み幅 `dt` は固定で、各ステップは
  `state → next_state` の陽的な写像として計算される
  （実装: `ProjectileSimulator._rk4_step()` / `nbody._rk4_step()`）。
- **適応刻みモード（`adaptive=True`、v5 で追加）**: 刻み幅の上限を `dt_max` とし、各ステップで
  必要なときのみ刻みを短縮する。**縮小のみで延長は行わない**
  （実装: `ProjectileSimulator._next_timestep()`）。

適応刻みモードは `ProjectileSimulator`（弾道・軌道）で利用できる。**N 体
（`NBodySimulator`）も `adaptive=True` で適応刻みを利用でき**、安定性上限の代わりに
最短ペア周期を用いる（→ 第26章）。

#### 3.2 安定性条件

陽的 RK4 の線形安定域の限界（無次元量 `z = dt·k·v`）から、以下を**安定性上限**とする。

```
dt_max = STABILITY_LIMIT / (k · v)          STABILITY_LIMIT = 0.5
```

`k` は抗力係数（第9章）。抗力が無い（`k = 0`）または速度が 0 の場合、安定性制約は
`inf` となり実質的な短縮は起きない（`ProjectileSimulator._stable_timestep()`）。このため
抗力無効な軌道の適応刻みは、呼び出し側が与えた `dt_max` をそのまま刻みとして使う。

初期条件での参考値（`k = 8.535522e-03`、`v0 = 47.2222`）では

```
dt_max ≈ 1.2405 s
```

`dt > dt_max` の場合（固定刻みモード）、`run_simulation()` は `RuntimeWarning` を発して続行する
が、**この警告は発散防止に過ぎず、精度の保証ではない**。適応刻みモードでは `dt_max` を超えない
ように自動的に短縮する。実測の到達距離誤差は概ね `(dt · k · v)²` に比例して増大するため、
精度を確保するには `dt_max` より十分小さい値（既定の 0.01 s は `dt_max` の約 1/124 で、
十分に安全側にある）が望ましい。適応刻みは発散を防ぐための機構であり、刻みを上限いっぱいまで
拡大した場合の精度を保証するものではない点に注意する。

#### 3.3 打ち切り条件と数値ガード（共通）

| 条件 | 挙動 |
|------|------|
| 時間上限 `max_time` | `timed_out = True` で停止、警告表示 |
| 発散（非有限値） | 状態成分に `NaN` / `Inf` → `SimulationDiverged` を送出 |
| 発散（速度異常） | 基準速度 × `divergence_speed_factor`（既定 `1000.0`）超 → `SimulationDiverged` を送出 |

- 速度の上限はモデルで異なる（弾道・軌道: `max(v0 × divergence_speed_factor,
  g × max_time)`、多体: `divergence_speed_factor` × 系内で最も速い天体の初速。
  全静止の系では速度ガードは無効）。
- `reset()` は初期状態・時刻・フラグ・ステップ数をすべて初期化する。`resume=True` で
  中断点から継続可能（終了済みの場合は no-op）。`resume` が偽のとき `run_simulation()` は
  常に先頭から再計算する（冪等）。
- モデル固有の打ち切り条件（地面交差、天体間の接近など）は各部に定める。

### 4. パラメータの外部定義

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

キーとモデルの対応は次のとおり。

| キー群 | 参照するモデル |
|--------|----------------|
| `max_time` | すべて（時間上限の既定。`NBodySimulator(max_time=None)` もこの既定を引く） |
| `gravity`, `air_density`, `mass`, `diameter`, `drag_coefficient` | 弾道の既定モデル（一定重力・一定密度抗力・Magnus 揚力） |
| `mu`, `j2`, `equatorial_radius` | 軌道（点質量重力・J2 扁平・高度算出） |
| `scale_height`, `sea_level_density` | `exponential_density()`（単一指数大気）。既定の層テーブルは使用しない |

既定の弾道モデル（一定重力・一定密度抗力）は `mu` / `j2` / `equatorial_radius` /
`scale_height` / `sea_level_density` を参照しない。多体は各天体の `mu` を呼び出し側が
与えるため、JSON の `mu` を参照しない（唯一の利用者は `max_time`）。

制約違反は dataclass の `__post_init__` で検証され、`TypeError` / `ValueError` を送出する。
未知のキーは `ValueError`（strict な検証）。JSON の構文エラーも `ValueError` に変換される。
**設定ファイルが不在の場合は警告とともに組み込み既定値へ退避する**（設定と独立に動作する）。

### 5. テスト体制

コアのテストは `range_calculator/` 直下にモジュール別に置く。総数は **200 件**。

| テストファイル | 件数 | 対象 |
|----------------|------|------|
| `test_range_calc.py` | 58 | 弾道（解析解との一致・基準シナリオ・ガード・設定・Magnus） |
| `test_adaptive_timestep.py` | 39 | 適応刻み（刻み上限・固定刻みとの一致・精度非保証・CLI） |
| `test_orbital.py` | 36 | 軌道（重力場・円/楕円軌道・軌道要素・密度/抗力モデル） |
| `test_nbody.py` | 67 | 多体（相互重力・2 体極限・保存量・ラグランジュ点・発散ガード・適応刻み） |

主要なテストクラスは次のとおり。

| ファイル | クラス |
|----------|--------|
| `test_range_calc.py` | `AnalyticAgreementTests` / `ConvergenceTests` / `LandingStateTests` / `PhysicsTests` / `RegressionTests` / `SimulatorContractTests` / `ConfigurationTests` / `ScenarioLoadingTests` / `NumericalGuardTests` / `MagnusLiftTests` |
| `test_adaptive_timestep.py` | `TimestepCeilingTests` / `AgreementWithFixedTimestepTests` / `StabilityAbsorptionTests` / `NoAccuracyClaimTests` / `LifecycleTests` / `EdgeCaseTests` / `CommandLineTests` |
| `test_orbital.py` | `NewtonianGravityFieldTests` / `GravityFieldAgreementTests` / `CircularOrbitTests` / `EllipticalOrbitTests` / `FromStateTests` / `OrbitalElementTests` / `J2GravityFieldTests` / `SumFieldsTests` / `DensityModelTests` / `DragModelTests` |
| `test_nbody.py` | `SingleBodyTests` / `MutualGravityFieldTests` / `SystemDerivativesTests` / `TwoBodyTests` / `KeplerLimitTests` / `ConservationTests` / `LagrangeTests` / `DiagnosticTests` / `ValidationTests` / `SingularityTests` / `DivergenceGuardTests` / `LifecycleTests` / `AdaptiveTimestepTests` / `ResultTimestepTests` / `ContractTests` |

テストはフラット import（`import ballistics` 等）を用いるため、カレントディレクトリに注意する
こと（リポジトリルートまたは `range_calculator/` のどちらからでも実行できる）。

```text
python3 -m unittest discover -s range_calculator -p "test_*.py"   # リポジトリルートから
python3 -m unittest test_range_calc                               # range_calculator/ から
```

Windows では `python3` の代わりに `python` でもよい（Scoop 構成では `python` と `python3` の
両方が有効。`py` は解決されない）。

各モデルが何を検証基準としているか（解析解・参照値）は、第13章（弾道）・第21章（軌道）・
第29章（多体）に定める。

### 6. 変更管理

物理定数・方程式を変更する場合、以下を遵守すること。

1. `physics_config.py` の `PhysicalParameters` にフィールドを追加する場合は、
   `PositiveFields` / `NonNegativeFields` の制約分類を必ず定義すること。
2. `config/physics_constants.json` に手を加えた場合は、該当するモデルの検証基準
   （第13章・第21章・第29章）の参照値を再計測して併せて更新すること。
3. 弾道の方程式（`derivatives()`）を変更した場合は、`k = 0` で閉形式に一致し続けることが
   必須である（`AnalyticAgreementTests` がこれを保証する）。
4. 軌道・多体の方程式を変更した場合は、保存量（軌道要素、エネルギー・運動量）と
   ライフサイクル契約が壊れないことを該当モジュールのテストで確認すること。
5. 各部の「適用限界」（第14章・第22章・第30章）に新しく「無視する物理効果」を追加した
   場合、その項目を本書に追記すること。
6. 新しいモデル（部）を追加する場合は、第I部の状態ベクトル・数値解法・パラメータ・
   テスト体制（第2章〜第5章）に組み込み、テスト件数を更新すること。

### 7. 開発環境と検証手順

- **Python**: 3.9 以上（標準ライブラリのみで動作する）。macOS / Windows 11 の
  Python 3.15 で検証している。Windows は Scoop 構成であり、`python` / `python3` で
  起動できる（`py` は解決されない。詳細は `docs/setup-windows.md` を参照）。
- **Node.js（`webapp` を使う場合のみ）**: 20.19 以上 / 22.12 以上（Vite 8 の要件）と
  npm。起動・ビルドは `webapp/README.md` を参照。物理コアのみを使う場合は不要。
- **デスクトップ GUI（`desktop` を使う場合のみ）**: 標準ライブラリの Tkinter のみで
  動作し、追加の `pip` パッケージは不要（実行ファイル化のビルド時のみ PyInstaller
  を使用）。起動・ビルドは `desktop/README.md` を参照。
- **テスト**: 第5章のコマンドを実行し、200 件すべてがパスすることを確認する。
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

## 第II部 弾道（`ballistics` / `range_calc`）

地表から発射した弾丸が、一定重力と 2 乗抗力のもとを飛行し地面に着地するまでの軌道を計算する。
**既定で有効なモデル**であり、CLI に追加フラグを与えずに実行される。

### 8. 解く問題と座標系

等質で球形の弾丸を、**大気が静止した地球上で**水平面に対して角度 θ（発射角）で初速度 `v0` で
発射したとき、**速度の 2 乗に比例する空気抵抗**を考慮して地面衝突までの距離と飛行時間を求める。
任意でスピンによる Magnus 揚力を加える（第9章 (c)）。

- 原点は射出点 `(LAUNCH_X, LAUNCH_Y, LAUNCH_Z)` = 既定 `(0, 0, 0)`。
- `x` は射程方向、`y` は鉛直上方向（地面は `y = 0`）、`z` は横方向（スピン時のみ非零）。
- 平面（平面 x-y）座標であり、地球の曲率は扱わない（→ 第14章 item 3）。
- 状態は位置と速度の 6 成分（第2章）。

### 9. 作用する力

自由飛行に対応する 2 つの力をモデル化し、任意で Magnus 揚力を加える。

#### (a) 重力

既定モデルでは座標系の鉛直下向き `-y` 方向に、質量によらず一定の加速度を与える。

```
ay = -g        g = 9.81 m/s^2
```

（`gravity` パラメータで変更可能。既定の平面弾道モデルは球面・緯度依存を考慮しない。
→ 第14章 item 2）

重力は加速度場 `gravity(state) -> (ax, ay, az)` として差し替え可能である
（内部表現: `GravityModel`、積分は `derivatives_with_gravity()`）。既定モデル
`constant_gravity()` は上記の一定加速度を返す。別の場へ差し替えると同じ積分器がそのまま
別の問題を解く — 軌道計算は `newtonian_gravity(mu)` / `j2_gravity()` をこの差し替えで
実現しており、詳細は第17章に定める。

#### (b) 空気抵抗（抗力）

速度ベクトルの**逆方向**に大きさが速度の 2 乗に比例する力。

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

抗力も加速度場 `drag(state) -> (ax, ay, az)`（内部表現: `DragModel`）として差し替え可能で、
既定の `constant_drag(k)` は上記の一定密度抗力に一致する。密度を高度の関数とする大気モデルは
軌道部に定義する（第18章）。弾道の CLI は高度依存大気を公開しないが、`drag_model=` を
直接与えれば利用できる。

#### (c) Magnus 揚力（スピン）

任意で回転による揚力を加える（既定はスピン 0 = 無効）。実装は `magnus_lift()`。

```
ω  = spin_rate · 2π/60                       （rpm → rad/s）
S  = |ω| · R / v                             R = 直径/2、v = |v|
C_L = min(slope · S, max)                    slope = 1.0, max = 0.3
a  = (1/2 · ρ · A · C_L / m) · v · (ŝ × v)
```

- 回転軸 `ŝ` は `spin_axis_vector(spin_axis_angle_deg)` が与える。軸は下流方向 `+x` まわりに
  回転させ、`0` でバックスピン（揚力は鉛直上）、`+90` で *+z*、`-90` で *-z*、
  `±180` でトップスピンになる。`spin_rate_rpm` の符号が揚力の向きを選ぶ。
- 揚力は常に速度に直交するため、軸を傾けると飛行が横に曲がる。
- スピン 0・速度 0 のとき場はゼロになるため、無条件に配線してよい。

これは回転球の空力に基づく厳密モデルではなく、定性的な左右・上下のずれを与える近似である
（→ 第14章 item 5）。CLI の指定は第15章の `--spin` / `--spin-axis`。

### 10. 時間発展方程式（微分方程式）

```
dx/dt  = vx
dy/dt  = vy
dz/dt  = vz
dvx/dt = -k · vx · |v|
dvy/dt = -k · vy · |v| - g
dvz/dt = -k · vz · |v|

|v| = sqrt(vx² + vy² + vz²)
```

この 6 元の 1 階連立 ODE を数値的に解く（`ballistics.derivatives()`）。
横方向 `z` / `vz` は `dvz/dt` が抗力のみでは零であり、Magnus 揚力を有効にしたときに初めて
駆動される（第9章 (c)）。

重力・抗力・揚力はいずれも加速度場であり、一般形は `derivatives_with_models()` に
まとまっている（第3章の RK4 はこの導関数を評価する）。

### 11. 初期条件と単位変換

| 項目 | 定義元（優先順） | 既定値 |
|------|------------------|--------|
| 発射速度 | `--v0=<km/h>` → `data.csv` 第1フィールド | 170.0 km/h |
| 発射角 | `--angle=<deg>` → `data.csv` 第2フィールド | 35.0 ° |
| 射出点 | `LAUNCH_X`, `LAUNCH_Y` | (0.0, 0.0) |

発射速度と発射角は**フィールド単位で独立に**解決される（`load_scenario()`）。
CLI オプションで与えられた項目はファイルを読まずに採用され、未指定の項目は `data.csv`、
そこからも読めない場合は既定値に落ちる。両オプションを指定した場合は `data.csv` を一切
読まない（欠損警告も発しない）。

```
v0_mps = velocity_kmph × 1000 / 3600          (170.0 km/h → 47.2222 m/s)
θ_rad  = radians(angle_deg)
vx0    = v0 · cos θ
vy0    = v0 · sin θ
```

初速 `v0` と発射角 `θ` は正の値を前提とする（負角・下向き発射は非対応。
負角を入力した場合は `launched_upwards` が偽となり、起動直後の着弾検出が 1 ステップ目の
ガードに掛からない点に注意）。データファイル `data.csv` は `velocity_kmph, angle_deg` の
1 行 CSV 形式。

構築方法は 2 通りある。

- `ProjectileSimulator(initial_velocity, launch_angle_rad, constants, dt, ...)` —
  射出点を原点とする弾道のパラメータ化。
- `ProjectileSimulator.from_state(state, constants, dt, ...)` — 明示的な状態から始める。
  軌道のように原点が中心天体である場面で使い、発射速度・角度は `state` から導出される
  （発散ガードの基準を保つため）。

### 12. 地面衝突と数値ガード

#### 12.1 地面衝突（`y = 0`）の扱い

各ステップ後に `y < 0` になった場合、そのステップ内の `y = 0` 交点を**線形補間**で求め、
衝突時の状態 `(x, y=0, z, vx, vy, vz)` を確定する（`_interpolate_ground_crossing()`）。
交点時刻は `t + ratio · dt`。補間比率 `ratio` は [0,1] にクランプされる。
`y` ちょうど 0 となる退化ケース（`span = 0`）では `ratio = 1.0` を採用する。

物理的な「着弾後の跳ね返り」は計算しない。1 回の地表面交差で終了する。

#### 12.2 打ち切り条件と数値ガード

| 条件 | 閾値 | 挙動 |
|------|------|------|
| 時間上限 | `max_time = 300 s` | `timed_out = True` で停止、警告表示 |
| 発散（非有限値） | 状態成分に `NaN`/`Inf` | `SimulationDiverged` を送出 |
| 発散（速度異常） | `max(v0 × 1000, g × max_time)` 超 | `SimulationDiverged` を送出 |
| 粗すぎる刻み | 第1ステップで上昇中発射が地面到達 | `ValueError` を送出 |

- `divergence_speed_factor = 1000.0`（倍率）は `ProjectileSimulator` のキーワード引数で上書き可。
  このガードは適応刻みモードでも有効（抗力が無くても縮む帯が無いため）。
- `FlightResult` は `ground_range` / `lateral_range` / `flight_time` / `impact_speed` /
  `landed` / `timed_out` / `steps` / `timestep_min` / `timestep_max` を持つ。
- `FlightResult.landed` は地面に到達した場合に `True`。
- `reset()` を呼び出すと、射出条件・時刻・フラグ・ステップ幅がすべて初期状態に戻る。

### 13. 検証基準（弾道）

#### 13.1 解の正当性（解析解との整合）

無抗力（真空）の理想射程には解析的な閉形式が存在するため、数値解と直接比較できる。

```
R_ideal = v0² · sin(2θ) / g
```

`v0 = 47.2222 m/s`, `θ = 35°`, `g = 9.81` のとき

```
R_ideal = 213.60 m
```

`ProjectileSimulator.calculate_ideal_range()` はこの値を返す。
`AnalyticAgreementTests` は `k = 0` で射程・飛行時間が閉形式と一致することを
`delta = 1e-4` で固定する（第6章 item 3）。

#### 13.2 参照ケース（基準シナリオ）

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

`k·v0²/g` は抗力加速度と重力加速度の初速時における比であり、これが 1 を超える場合は飛行の
初期段階で抗力が重力を上回る。本ケースでは 1.94 であり、抗力の影響は無視できない領域にある。
`k·v0²/g ≫ 1` では `R_ideal` からの乖離が指数的に増大するため、無抗力解を近似として
用いてはならない。

#### 13.3 その他の固定事項

- `ConvergenceTests` — 着弾補間により `dt = 0.01` と `dt = 0.0001` で結果が一致すること。
- `PhysicsTests` — 抗力による射程短縮、最適角度が 45° 未満になること。
- `LandingStateTests` — 着弾状態（`y = 0`、下降中、水平発射で原着弾）の妥当性。
- `RegressionTests` — 基準シナリオの射程 101.12 m・飛行時間 4.37 s に一致すること。
- `MagnusLiftTests` — スピン軸ベクトル、Magnus 揚力による横ずれ `z`、回転数 0 での無効化。
- `NumericalGuardTests` / `SimulatorContractTests` — 発散検出、粗すぎる刻みの警告・例外、
  `reset()` / `resume` の契約整合・冪等性、引数検証、コアモジュールの I/O 禁止。
- `ConfigurationTests` / `ScenarioLoadingTests` — 付属設定と組み込み既定値の一致、
  `drag_scaling_factor` の往復、レガシー互換マッピング、設定の上書きが積分に届くこと、
  設定不在時の既定値退避、未知キー・不正 JSON・非正値の拒否、
  `data.csv` の読み込み・欠損・不正・余分な列のときのフォールバック、CLI の実行。

適応刻みモード（`adaptive=True`）は、安定性帯内では固定刻みと一致し、安定性帯を超える
`dt_max` でも発散せず完走するが、精度改善を保証しない点が `test_adaptive_timestep.py` で
固定されている。

### 14. 適用限界（弾道）

以下は本モデルが**意図的に考慮していない**項目であり、結果の解釈範囲を限定する。

1. **高度依存の大気密度** — 既定モデルは `ρ` を一定（1.225）とするため、高打球では実際より
   抗力を過大評価する。高度依存大気（第18章）は `drag_model=` として差し替えれば扱えるが、
   弾道の CLI はこの切り替えを公開しない。層テーブル・単一指数とも代表値であり、
   温度・太陽活動依存は考慮しない。
2. **重力の実高度・緯度依存** — 既定モデルは `g` を 9.81 一定とする（実際の上昇では約 1%
   減衰）。球面重力モデル（第17章）へ切り替えれば高度依存（逆二乗則）は扱える。
   J2 扁平（第17章）で扁平（帯球）項も加えられるが、緯度依存の高次項・遠心力は考慮しない。
3. **地形の曲率（地球の球面性）** — 平面 x-y 座標を用いる。本ツールの基準ケースでは
   射程 101 m であり、地球の曲率による高低差は最大約 0.8 mm（0.0008 %）に留まるため
   影響は実用的に無視できる。射程が 10 km 規模に達すると高低差は約 8 m となり、
   誤差が顕在化する。
4. **風・突風・空気の移流** — 大気静止を仮定。
5. **回転による揚力（Magnus 効果）・スピンの軌道への影響** — 既定では無視（スピン 0）。
   任意で簡易モデルを有効化できる（第9章 (c)）が、実測の回転球空力に基づく厳密モデルでは
   なく、定性的な左右・上下のずれを与える近似である。
6. **反発係数・跳ね返り** — 初衝突で計算終了。
7. **温度・湿度による `Cd` と `ρ` の変動** — 固定値とする。
8. **形状による抗力係数の変動** — `Cd = 0.47` を定数とする（球体近傍の代表値）。
9. **`Cd = 0.47` と球径・質量の整合性** — 質量 149 g / 直径 75 mm は野球ボール相当だが、
   野球ボールの実測 `Cd` は自由飛行でおおむね 0.33–0.36、風洞実験では球種により 0.3 前後
   まで低下する（例: NPB）。本値は直径 75 mm・平滑な球に対する実験値であり、**どの球種を
   想定した値かを定量的な出典で確認するまで、本値は暫定値として扱う**。
   既定プロファイルの質量 149 g・直径 75 mm は野球ボールの公認寸法（質量 141.7–148.8 g、
   円周 22.9–23.5 cm）に基づく値であり、`Cd = 0.47` はこのサイズ・質量の球体に対する
   代表値である。球種を限定した実測値（MLB 自由飛行: 0.348/0.358、NPB 風洞: MLB より低値）
   は回転・風洞条件に依存するため本ツールでは採らず、**`Cd = 0.47`（球体代表値）に固定**
   する。Web アプリ（`webapp/README.md`）・デスクトップ GUI とも `drag_coefficient` は
   この既定値を送信し、UI に球種プリセットの選択は設けない。
10. **縮尺効果（直径依存 Reynolds 数）** — 高速域での `Cd` 変化は考慮しない。

### 15. CLI 仕様（弾道）

```text
python range_calc.py [scenario_path] [dt_max] [--adaptive] [--v0=<km/h>] [--angle=<deg>]
python range_calc.py --spin=<rpm> [--spin-axis=<deg>] [--v0=<km/h>] [--angle=<deg>]
```

- `scenario_path`: `data.csv` のパス（省略可）。指定しない場合は同ディレクトリの `data.csv`
  を読み込む。
- `dt_max`: タイムステップの上限値（秒）。省略した場合は `0.01` s。
- `--adaptive`: 指定すると適応刻みモードを有効にする。省略した場合は固定刻みモードとなり、
  **挙動は v4 と完全に同一**である。
- `--v0=<km/h>`: 初速の上書き（単位 km/h）。**`=` 書式のみ受理**（`--v0 160` はエラー）。
  省略時は第11章の定義元に従う。
- `--angle=<deg>`: 発射角の上書き（単位 °）。書式・省略時の挙動は `--v0` と同じ。
  両オプションともフィールド単位で独立にフォールバックし（引数 → CSV → 既定値）、
  両方指定した場合は `data.csv` を読まない。不正値・`=` なし・重複指定は `SystemExit` で
  拒否される。
- `--spin=<rpm>`: Magnus 揚力を加える（第9章 (c)）。`0` 以外を指定すると
  `magnus_lift(DEFAULT_PARAMETERS, spin, axis)` が有効になり、出力に `Spin Rate` /
  `Spin Axis Angle` と横ずれ `Lateral Deflection` が加わる。
- `--spin-axis=<deg>`: 回転軸を下流軸まわりに傾ける角度（deg）。省略時は `0`。
  `--spin` と併用する。

出力は `--- Simulation Results ---` / `--- Range Comparison ---` に加え、
`Ideal Range (No Drag)` / `Realistic Range` / `Actual Flight Time` / `Integration Steps`、
適応刻み時に `Shortest Step Taken`、時間上限到達時に WARNING を表示する。

軌道モード用フラグ（`--orbital` / `--radius` / `--j2` / `--atmosphere`）は弾道モードでは
解析されるが使用されない（第23章）。

---

## 第III部 軌道（`orbital` / `ballistics` の重力・抗力モデル）

中心天体の重力場に置かれた 1 天体の軌道を積分し、その状態を軌道要素へ換算する。
第II部と同じ `ProjectileSimulator` を使うが、**原点を中心天体の中心に置き、重力場を
差し替えて地面交差判定を切る**ことで実現する。

### 16. 解く問題と座標系

中心天体を原点とする座標系で、点質量重力（および任意で J2 扁平・高度依存大気）のもと
軌道を積分し、その状態を軌道要素（第19章）へ換算する。

- 原点は中心天体の中心。位置 `r = (x, y, z)` は中心からのオフセット、速度 `v` はその点での
  絶対速度。
- 球面（3 次元）座標であり、極軸は `z` 軸（J2 の対称軸）とする。
- **地面が存在しない**: `ground_collision=False` で実行する（第20章）。大気モデルを有効に
  した場合でも、天体表面（`|r| < equatorial_radius`）への落下は検出されない
  （→ 第22章）。
- 状態は位置と速度の 6 成分（第2章）。

### 17. 重力場

重力は加速度場 `GravityModel = Callable[[State], (ax, ay, az)]` として実装され、
呼び出し側の `gravity_model=` に差し替えて使う（第9章 (a) と同じ機構）。

#### (a) 点質量（ニュートン重力）

原点へ向かう逆二乗則を与える。

```
a = -mu · r / |r|³        r = (x, y, z),  mu = 中心天体の G·M
```

実装は `newtonian_gravity(mu)`。標準重力パラメータは `mu` パラメータ
（既定: 地球の `3.986004418e14` m³/s²）で与える。

#### (b) J2 扁平摂動

`j2_gravity(mu, j2, equatorial_radius)` は点質量項に第 2 帯球関数（扁平）項を加えた場を
返す。極軸は座標 `z` 軸とし、`s = z/|r|` として

```
a_J2 = -(3/2) · J2 · mu · R² / |r|⁵ · ( (1-5s²)x, (1-5s²)y, (3-5s²)z )
```

`J2` は `J2_EARTH = 1.08263e-3`、`R`（`equatorial_radius`）は地球赤道半径 `6.378137e6` m を
既定とする。`j2 = 0` のとき場は厳密に `newtonian_gravity(mu)` と一致する
（摂動は完全に任意）。

#### (c) 場の合成

`sum_fields(*fields)` は任意個の加速度場を成分ごとに加算した場を返す。
各中心天体を独立の `mu` / `j2` 場として与えれば**複数の固定した中心**を持つ問題へ拡張できる。

ただし固定場の合成は天体の位置を評価しないため、互いに動く天体の問題は解けない。
その場合の正しい機構は `nbody.mutual_gravity()`（第25章）である。

### 18. 高度依存の抗力（大気モデル）

抗力は加速度場 `DragModel = Callable[[State], (ax, ay, az)]` であり、密度を高度の関数と
することで高度依存を扱う。

```
DensityModel = Callable[[float], float]        a_drag = -k(h) · v · |v|
k(h) = (1/2 · ρ(h) · A · Cd) / m
```

密度モデルは次の 3 種。

| 関数 | 定義 |
|------|------|
| `constant_density(rho)` | `ρ(h) = rho`（高度に依存しない。既定の弾道モデル） |
| `exponential_density(rho0, H, h0=0)` | `ρ(h) = rho0 · exp(-(h-h0)/H)`（単一スケールハイト近似） |
| `tabulated_density(layers)` | `(基準高度, rho, H)` 層テーブルによる区分指数近似 |

`atmospheric_drag(parameters, density_model, altitude)` は `altitude(state)` で得た高度から
`k(h)` を評価し、`derivatives_with_models()` 経由で積分に渡される。高度の取り方には
`orbital_altitude(R) = |r| - R`（球面。軌道用）と `flat_altitude() = y`（平面。弾道用）が
ある。

既定の層テーブル `EARTH_ATMOSPHERE_LAYERS` は 28 層、0–1000 km の区分指数フィットである
（各層は `(基準高度, 基準密度, スケールハイト)`。基準密度・スケールハイトは
`scale_height` / `sea_level_density` とは独立の代表値）。層の選択は基準高度以下のうち
最も高い層を用い、`rho_base · exp(-(h - base)/H)` を評価する。

`tabulated_density()` は空テーブル・非正のスケールハイト・負の密度を拒否する。

### 19. 軌道要素（`orbital.py`）

ニュートン重力での軌道は、位置 `r`・速度 `v` と中心天体の `mu` から**軌道要素**
（`OrbitalElements`、`orbital_elements(state, mu)`）として解析的に表せる。
同じ計算が円・楕円・放物・双曲のすべてに成立する（エネルギーと偏心率・角運動量ベクトルから
導出するため、軌道の型を分岐しない）。

| 要素 | 定義 |
|------|------|
| `specific_energy` | 比エネルギー `ε = |v|²/2 − μ/|r|` |
| `semi_major_axis` | 長半径 `a = −μ/(2ε)`（放物線 `ε = 0` では `None`） |
| `eccentricity` | 離心率 `e = |e_vec|`、`e_vec = ((|v|² − μ/|r|) r − (r·v) v)/μ` |
| `periapsis` | 近点半径 `r_p = h²/(μ(1+e))`、`h = |r × v|` |
| `apoapsis` | 遠点半径 `a(1+e)`（開軌道 `e ≥ 1` では `None`） |
| `period` | 公転周期 `T = 2π√(a³/μ)`（開軌道では `None`） |
| `inclination_rad` | 軌道傾斜角 `acos(h_z/h)` |

- `|r| = 0`（中心天体上）や `mu ≤ 0` は定義できないため `ValueError` を送出する。
- 円軌道（`e ≈ 0`）では `r_p ≈ r_a ≈ a` となる。
- 開軌道（`e ≥ 1`）では `semi_major_axis` / `apoapsis` / `period` が `None` となり、
  出力では `n/a` と表示される（`_format_optional()`）。
- 角運動量が 0 のとき（直進）は `inclination_rad = 0.0` とし、`acos` の定義域は
  [-1, 1] にクリップする。

摂動（J2・大気）を有効にした場合、この要素はその時点の状態に対する**瞬間的（osculating）**
な値であり、軌道全体を一意に定める量ではない。

### 20. 初期条件と実行方法

| 項目 | 定義元 | 既定値 |
|------|--------|--------|
| 初期半径 | `--radius=<m>` | `7.0e6` m |
| 初速 | `--v0=<km/h>` → `data.csv` 第1フィールド → 既定 | 170.0 km/h → 47.2222 m/s |
| 高度の基準 | `equatorial_radius` | 6378137.0 m |

初期状態は **+x 軸上に半径 `radius`、速度は軌道接線方向**に置く。

```
state = (radius, 0, 0, 0, v0_mps, 0)
```

`--angle` は軌道モードでは無視される。実装は
`ProjectileSimulator.from_state(state, constants, dt, adaptive=..., gravity_model=...,
drag_model=..., ground_collision=False)` で、発射速度・角度は `state` から導出される
（発散ガードの基準を保つため）。

初期速度は第11章と同じ定義元（`--v0` → `data.csv` → 既定 170 km/h = 47.2222 m/s）で
解決されるため、**既定値は円軌道速度と一致しない**（半径 7.0e6 m の円軌道速度は
`sqrt(mu / radius)` ≈ 7546 m/s）。CLI は両方を出し分け、
`Initial Speed` / `Circular Speed`（`sqrt(mu / radius)`）を参考表示する。
既定の半径 7.0e6 m は地表ぎりぎり（地球半径 6.378137e6 m + 高度約 622 km）に相当する。

抗力の既定は**無効**（`drag_coefficient = 0`）である。`--atmosphere` を与えた場合のみ
区分指数大気を有効にする（第18章）。重力の既定は `newtonian_gravity(mu)`、`--j2` を与えた
場合のみ `j2_gravity(mu, j2, equatorial_radius)`（第17章）になる。

抗力が無いため `k = 0` となり、適応刻みモードでも安定性制約による短縮は起きない
（第3章 3.2 節）。`--adaptive` の指定は軌道モードでは実質的に効かない。

### 21. 検証基準（軌道）

すべて `test_orbital.py`（36 件）で固定する。

#### 21.1 重力場

- 逆二乗則: 半径を 2 倍すると加速度が 1/4（`near / far = 4.0`、`places=9`）。
- `j2_gravity(mu, 0.0)` は `newtonian_gravity(mu)` と全成分一致（`places=12`）。
- J2 の向き: 赤道上では点質量より弱く、極上では点質量より強いこと。
- `j2_gravity()` の既定は地球定数（`J2_EARTH`, `EQUATORIAL_RADIUS_EARTH`）と一致。
- `sum_fields()` は成分ごとに加算され、空の合成はゼロ場。

#### 21.2 軌道の積分

基準ケースは `mu = 3.986004418e14`、`radius = 7.0e6 m`。

- **円軌道** — 初速 `sqrt(mu/r)`、周期 `T = 2πr/v`。RK4 でも
  - 全ステップで半径の相対変動が `1e-4` 未満。
  - 1 周期後に初期位置へ戻る（`|y| < 1e3` m、`hypot(x, y) = radius` に `delta=1e3` m）。
  - 地面に着地せず時間上限まで走り切る（`timed_out = True`, `landed = False`）。
- **楕円軌道** — 近地点 `7.0e6 m` / 遠地点 `42.0e6 m` から出発。
  - 積分中の最小・最大半径がそれぞれ近地点・遠地点に `delta=1e3` m で一致。
  - 4 分の 1 周期経過後も長半径が `delta=1e3` m、離心率が `places=6` で保たれる。

#### 21.3 軌道要素

- 円軌道: `e = 0.0`（`places=12`）、`a = r_p = r_a = r`（`places=6`）、
  `T = 2π√(r³/μ)`（`places=6`）、`ε = −μ/(2r)`、傾斜 `0.0`（`places=12`）。
- 楕円軌道: `e`・`a`・`r_p`・`r_a`・`T` すべてが閉形式と `places=3`〜`12` で一致。
- 傾斜角: `0° / 30° / 63.4° / 90°` の入力に対し `places=9` で再現。
- 双曲軌道: `e > 1.0`、`ε > 0`、`apoapsis` / `period` が `None`。

#### 21.4 場の抽象と大気モデル

- **場の抽象** — 加速度場版
  `derivatives_with_gravity(state, k, constant_gravity(9.81))` はスカラー重力版
  `derivatives(state, k, 9.81)` と全成分一致し、既定の場は `(0, -9.81, 0)`
  （`GravityFieldAgreementTests`）。
- **`from_state()`** — 明示した状態を `initial_state` と `state` の両方に設定し、
  既定では平面弾道の場（`constant_gravity`）を使う（`FromStateTests`）。
- **密度モデル** — `constant_density` は高度に非依存。`exponential_density(1.225, 8500)`
  は `ρ(0) = 1.225`、`ρ(8500) = 1.225/e`（`places=9`）で閉形式と一致し単調減少し、
  スケールハイト 0 は `ValueError`。`tabulated_density(EARTH_ATMOSPHERE_LAYERS)` は
  0 → 50 km → 200 km → 1000 km で単調減少し、層の基準高度では `rho` に一致、
  基準高度 + スケールハイトでは `rho / e`（`places=15`）。空テーブル・非正のスケール・
  負の密度は `ValueError`（`DensityModelTests`）。
- **抗力モデル** — `constant_drag(k)` 付きの `derivatives_with_models()` は従来の
  `derivatives(state, k, 9.81)` と `places=12` で一致し、抗力なしが指定された場合は
  無抗力場 `derivatives_with_gravity(state, 0.0, gravity)` と同一。抗力は速度に逆方向
  （`ax < 0`, `ay > 0`, `az < 0`）。`atmospheric_drag()` は密度 0 でゼロ場、
  密度 1.0 で非ゼロ。`orbital_altitude(R)` は `|r| − R`、`flat_altitude()` は `y` を
  返す（`DragModelTests`）。

### 22. 適用限界（軌道）

1. **中心天体は点質量 + J2 のみ** — 重力ポテンシャルの高次項（J3 以降）、
   地球の重力場の空間変動、他の天体の摂動（潮汐・第三天体）は考慮しない。
   複数の固定中心が必要なら `sum_fields()`（第17章 (c)）、動く中心なら多体
   （第IV部）を使う。
2. **表面・大気圏への落下は検出しない** — `ground_collision=False` のため、
   近地点が中心天体半径を割っても軌道計算は続行し、天体をすり抜ける。
3. **2 体の力学として扱う** — 積分する天体の自身の自転・変形はなく、
   他の既知の天体との引力は場として加えない。
4. **大気モデルは代表値** — `EARTH_ATMOSPHERE_LAYERS`・`exponential_density()` は
   層ごとの代表値であり、温度・季節・太陽活動による変動を含まない
   （→ 第18章）。
5. **摂動下の軌道要素は瞬間値** — J2・大気を有効にしたとき、`orbital_elements()` の値は
   その時点の状態に対する osculating 値であり、軌道遷移（近日点移動など）の軌跡として
   使うには積分中の各ステップで評価する必要がある（第19章）。
6. **安定性制約が働かない** — 抗力が無ければ `k = 0` となり、適応刻みの短縮が起きない
   （第3章 3.2 節）。刻み幅は利用者が選ぶ責任を持つ。
7. **長時間積分の精度** — 非シンプレクティックな RK4 のため、長期ではエネルギーが
   漂流する（→ 第30章と同じ制約）。

### 23. CLI 仕様（軌道）

```text
python range_calc.py --orbital [--radius=<m>] [--v0=<km/h>] [--adaptive] [--j2] [--atmosphere]
```

- `--orbital`: 地表弾道の代わりに中心重力場の軌道を積分する。初期状態は +x 軸上の
  `--radius` に置かれ、初速は軌道接線方向（`--angle` は無視）となる。
  `ground_collision=False` で実行され、実行後に軌道要素（`orbital_elements()`）を出力する。
  摂動フラグを付けない場合は抗力無効・`newtonian_gravity(mu)`（閉軌道）となる。
- `--radius=<m>`: 軌道モードの初期半径（単位 m）。既定値 `7.0e6` m。
  `0` 以下は `SystemExit` で拒否される。
- `--j2`: 軌道モードの重力を `j2_gravity(mu, j2, equatorial_radius)`（扁平摂動つき）にする。
- `--atmosphere`: 軌道モードの抗力に区分指数大気
  （`tabulated_density(EARTH_ATMOSPHERE_LAYERS)`）を有効にする。省略時は抗力無効
  （`drag_coefficient = 0`）で、`--j2` と独立に指定できる。
- `--v0` / `--adaptive` / `dt_max` / `scenario_path`: 第15章と同じ扱い。
  ただし `--angle` は無視され、`--spin` は軌道モードでは使用されない。

出力は `--- Orbital Simulation ---`（Gravity Model / Atmosphere / Central mu /
Initial Radius / Initial Speed / Circular Speed / Timestep Ceiling）、
`--- Orbital Elements ---`（7 要素、`None` は `n/a`）、
`--- Integration ---`（Flight Time / Integration Steps / Shortest Step Taken）。

`--j2` / `--atmosphere` / `--radius` / `--spin` は `--orbital` なしでは解析されるが
**使用されない**（エラーにはならず、弾道モードは既定のまま実行される）。

---

## 第IV部 多体（`nbody`）

複数天体の相互重力による完全 N 体問題を積分する。**天体は互いに自由落ち、固定された
中心点は存在しない**点が、第III部の固定場（`sum_fields()`）と決定的に異なる。

### 24. 解く問題と状態ベクトル

完全 N 体の相互重力は、各天体を点質量として `mu_i = G*M_i`（`ballistics.newtonian_gravity`
と同じ単位系）とし、6N 元状態で積分する。

```
a_i = \sum_{j != i} mu_j * (r_j - r_i) / |r_j - r_i|^3,  i=1,...,N
```

- 状態は `SystemState = tuple[State, ...]`（各要素が天体ごとの位置と速度の 6 成分）。単位は SI 一貫。
- 天体は `Body(mu, state)`（`mu` は G·M、m³/s²）で表す。**動力学に質量そのものは不要**で、
  `mu` だけで十分（診断量では `G = 1`・質量 ≡ `mu` の単位系を使う。→ 第28章）。
- 実装は `nbody`。リポジトリにファイル I/O は無い（初期条件は呼び出し側が与える）。

### 25. 相互重力

`mutual_gravity(mus, min_separation=0.0)` が `SystemField = Callable[[SystemState],
SystemAccelerations]` を返す。加速度は各対について**現在の位置**で評価する
（第17章 (c) の `sum_fields()` が単一の状態に対して固定した中心を評価するのと対照）。

```
a_i = \sum_{j != i} mu_j * (r_j - r_i) / |r_j - r_i|^3
```

- `len(system) != len(mus)` のときは `ValueError`。
- 2 天体が**完全に一致**（`|r_i - r_j| = 0`）すると特異となるため、構築時・場の評価時の
  どちらでも常に拒否する。
- `min_separation > 0` を指定すると、対がそれより近づいた時点で
  `SimulationDiverged` を送出する。モデリング不能な接近を数値的な見かけ上の安定と誤認
  せず、はっきり失敗させるための機構である。

`system_derivatives(system, gravity)` は各天体の導関数
`(vx, vy, vz, ax, ay, az)` を組み立てる（`ballistics.derivatives_with_models()` と同形）。

### 26. 数値解法と制約

`NBodySimulator` は**古典的 RK4**で 6N 元の連立 ODE を積分する。

- **固定刻みモード（`adaptive=False`、既定）**: 刻み幅 `dt` は固定。
- **適応刻みモード（`adaptive=True`）**: `dt` を**上限**とし、各ステップで最も緊密な対の
  周期 `T = 2π√(r³ / (mu_i + mu_j))` から
  `h = T / ADAPTIVE_STEPS_PER_PERIOD`（`ADAPTIVE_STEPS_PER_PERIOD = 100`）を計算し、
  `h = min(dt, h)` とする。**縮小のみで延長は行わない**。周期は毎ステップの現在状態から
  求めるため、接近時に自動で刻みが細かくなる。
  - `ProjectileSimulator` の安定性帯は抗力係数から導かれるもので N 体には対応しないため、
    N 体は**周期の 1/100 ステップ**という別の基準を用いる（RK4 のエネルギー漂移は
    1 周期あたりのステップ数 `n` に対し概ね `n⁻⁴` で減るので、`n = 100` で
    1 周あたり約 `1e-6` を狙う。精度の保証ではなく発散防止と実用的な保存性のため）。
  - 単一の天体など対が無い系では短縮は起きず `dt` をそのまま使う。
  - `result()` の `timestep_min` / `timestep_max` に実際に用いた刻みの最小・最大を返す
    （固定刻みではどちらも `dt`。ただし最終ステップが `max_time` に合わせてトリムされた
    場合は `timestep_min` のみ `dt` より小さくなる。未実行時は `None`）。
- 固定刻みで使う場合、刻み幅 `dt` はシステム中最も速いダイナミカル時間スケールに対して
  十分小さく選ぶこと。目安は最も緊密な対の周期
  `T = 2π√(r³ / (mu_i + mu_j))`。
- 最終ステップは `max_time` を超えないようトリムされ、その後 `timed_out = True` となる
  （第3章 3.3 節の共通ガード）。
- ハードガードは 2 つ: 非有限値、`divergence_speed_factor`（既定 1000.0）倍を超える速度。
  どちらも `SimulationDiverged` を送出する。基準速度は初期状態で最も速い天体の速度で、
  **全静止の系では速度ガードは無効**になり、有限値ガードのみが働く（静止からの崩壊は
  特異点ガードと有限値ガードが捕捉する）。
- **最後の段階で 1 つでも非有限値になった場合は、その時点の状態を採用せずに失敗させる**。
- **RK4 は非シンプレクティック**なので、長期積分では総エネルギーが漂流する
  （→ 第29章 29.3 節の刻み依存性、第30章 item 4）。

### 27. 初期条件とライフサイクル

| 項目 | 引数 | 既定値 |
|------|------|--------|
| 天体 | `bodies: Sequence[Body]` | （必須。1 個以上） |
| 刻み幅 | `dt` | `0.01` s |
| 時間上限 | `max_time` | `None` → `DEFAULT_PARAMETERS.max_time`（300 s） |
| 適応刻み | `adaptive` | `False`（`dt` を固定刻みとして使う） |
| 速度ガード倍率 | `divergence_speed_factor` | `1000.0` |
| 最小間隔 | `min_separation` | `0.0`（0 = 精密一致のみ拒否） |
| 重力場 | `gravity_model` | `None` → `mutual_gravity(mus, min_separation)` |

構築時に検証される: 天体が 1 個以上、各 `mu` が正かつ有限、状態 6 成分が有限、
2 天体の初期位置が一致しないこと。`min_separation` が負なら `ValueError`。

ライフサイクル:

- `run_simulation(dt=None, resume=False, *, on_step=None) -> float` — `max_time` まで積分し
  経過時刻を返す。`on_step(t, system)` は初期系と各受理系について呼ばれる純粋な観測フックで、
  系は不変タプルなのでコピーせずに参照を保持できる（`None` なら記録しない）。
- `reset()` — 初期系へ戻し、**呼び出し側が `run_simulation` に渡した刻み幅の上書きも破棄する**
  （失敗した実行が原因の刻み幅を残さないため）。
- `resume=True` で中断点から継続（`timed_out` のとき即 `return`）。偽なら毎回先頭から
  再計算する（冪等。`ProjectileSimulator` と同じ契約）。
- `bodies` プロパティは現在の各天体を `Body(mu, state)` として返し、第28章の診断関数に
  渡せる。
- `result()` は `SystemResult(elapsed_time, steps, timed_out, timestep_min, timestep_max)`
  を返す。`timestep_min` / `timestep_max` は実際に用いた刻みの最小・最大で、固定刻みでは
  どちらも `dt`（最終ステップのトリム時のみ `timestep_min` が小さくなる）、未実行時は
  `None`（適応刻みの効果を確認するための診断値）。
  弾道の `FlightResult`（第12章）とは異なり、着弾・衝突の概念を持たない。

### 28. 診断量

`nbody` は保存量の検証用に 4 つの診断関数を提供する。

| 関数 | 内容 |
|------|------|
| `total_energy(bodies)` | 運動エネルギー + 相互ポテンシャルエネルギー |
| `linear_momentum(bodies)` | 全運動量ベクトル |
| `angular_momentum(bodies)` | 全角運動量ベクトル |
| `center_of_mass(bodies)` | 質量中心 |

**これらの値は `G = 1`・質量 ≡ `mu` の単位系で評価される**。値そのものは単位系の
選択に依存するが、積分を通じた**定数性は任意の単位系で物理的に意味を持つ**。

### 29. 検証基準（多体）

すべて `test_nbody.py`（67 件）で固定する。

#### 29.1 基礎場と微分

- 2 天体 `mu = 1` / `mu = 2`、間隔 3 のときの加速度が `2/9` と `-1/9`
  （`places=12`）に一致。逆二乗則は半径比 2 で 4 倍。
- 単一の天体は相互作用が無く、`dt = 0.01` / `max_time = 10` で `steps = 1001`、
  終了時も速度 `(1, 2, 3)` m/s を保持する。
- `system_derivatives()` の形は各天体 `(vx, vy, vz, ax, ay, az)`。

#### 29.2 2 体極限とケプラー極限

- `nbody` の 2 天体解は `ballistics.newtonian_gravity(mu)` の中心場解に
  `delta=1e-6` で一致する（`TwoBodyTests`）。
- 重い天体（`mu = 1e6`）と軽い天体（`mu = 1`）、間隔 1 の円軌道を 1 周期積分して
  - 間隔の変動が `1e-6` 未満、
  - 軽い天体の初期位置からの変位が `1e-6` 未満、
  - 重い天体の揺れが `1e-10` 未満かつ軽い天体の移動の `1/1000` 未満。

#### 29.3 保存量

等辺三角形のラグランジュ配置（3 つの等質量 `mu = 1`、辺 1）を 4 分の 1 周期積分して
`dt = 1e-3` で評価する。

- 運動量: 各成分が `delta=1e-12` で保存。
- 角運動量: 各成分が `delta=1e-12` で保存。初期値は閉形式 `√3` と `places=12` で一致
  （`z` 成分のみ非零）。
- エネルギー: ドリフトが `1e-9` 未満。初期値は 3 単位質量が互いに距離 1 にある閉形式
  `−1.5` と `places=12` で一致。
- **刻みを細かくするとドリフトが減る**: `dt = 1e-1` と `dt = 1e-2` で 10 分の 1 に
  細かくすると、エネルギー誤差が `1e3` 倍以上改善する（RK4 の誤差が `O(dt⁴)` であることの
  確認。粗い方のドリフトは `1e-7` を超える）。

#### 29.4 形状の保持（ラグランジュ点）

- 等辺三角形は 1 周期後も全対の間隔が `delta=1e-6` m で保たれ、各天体は初期位置へ
  `delta=1e-6` で戻る。
- 辺長が 4 倍になると回転周期が 8 倍（`slow / fast = 8.0`、`places=12`）。
  閉形式 `T = 2π√(side³ / (3 mu))` と一致する。
- 質量中心は静止し、全静止系の運動量・角運動量はゼロのまま。

#### 29.5 ガードとライフサイクルの契約

- **診断量の契約**（`DiagnosticTests`）— 重なり合う天体・空の系は拒否、質量中心は
  `mu` で加重される、静止した天体の運動量・角運動量はゼロ、
  `bodies` プロパティは現在の状態を返す。
- **構築時検証**（`ValidationTests`）— 空の系・非シーケンス・`Body` でない要素・
  非正または非有限の `mu`・壊れた状態・重複した初期位置・`min_separation` より近い
  初期位置・不正な `dt` と上限を、積分が始まる前にすべて拒否する。
  リストで与えた状態はタプルへ変換される。
- **特異点**（`SingularityTests`）— `min_separation` があると正面衝突は
  `SimulationDiverged` で停止する。ガードが無いと天体はすり抜ける。
  ガードの有無で挙動が変わることを対にして固定している。
- **発散ガード**（`DivergenceGuardTests`）— 非有限な力、速度の爆発、
  `divergence_speed_factor` を広げると許容範囲も広がること、
  および全静止系には速度基準が無く有限値ガードのみが働くことを固定する。
- **ライフサイクル**（`LifecycleTests`）— 繰り返し実行の冪等性、`reset()` による初期系の
  復元、`timed_out` 後の `resume` が no-op、`on_step` が初期系と各受理系を観測すること、
  刻み幅上書きの検証、`result()` のカウンタ。
- **モジュール境界**（`ContractTests`）— `nbody` はファイル I/O を行わない
  （`ballistics` と同じ境界）。

#### 29.6 適応刻み（`AdaptiveTimestepTests` / `ResultTimestepTests`）

- `adaptive=True` では各ステップの刻みが `dt` を超えない。
- `dt` が最短ペア周期に対して粗い場合、適応刻みは `dt` より小さい刻みを選び、
  ステップ数が増える。
- `dt` が適応上限（`T / 100`）以下のときは固定刻みと一致する（`assertEqual` で
  ステップ数・最終状態まで同一）。
- 単一の天体など相互作用の無い系では短縮が起きず `dt` をそのまま使う。
- 円軌道を 1 周期積分したときのステップ数は `ADAPTIVE_STEPS_PER_PERIOD` 以上になる。
- 粗い `dt`（`dt ≫ T / 100`）でも適応刻みはエネルギー漂移を
  `1e-5` 未満に抑える（1 周あたり概ね `1e-6`）。
- `result()` の `timestep_min` / `timestep_max` は未実行時に `None`、固定刻みでは
  どちらも `dt` を返す（最終ステップのトリム時を除く）。

### 30. 適用限界（多体）

1. **点質量モデル** — 回転・潮汐・変形・内部構造は考慮しない。
2. **衝突はモデル化しない** — 2 天体の完全一致は特異として拒否するが、衝突そのもの
   （合体・反発）は計算しない。`min_separation > 0` で接近そのものを失敗として扱える。
3. **固定刻みでは刻み幅の選択は呼び出し側の責任** — `adaptive=False` では安定性・精度は
   完全に `dt` に依存する（第26章）。`adaptive=True` は最短ペア周期の `1/100` まで自動で
   短縮するが、これは発散防止と実用的な保存性のための機構であり、**精度の保証ではない**。
4. **RK4 は非シンプレクティック** — 長期積分では総エネルギーが漂流する。エネルギー保存が
   目的なら `dt` を細かくするか適応刻みを有効にし、それでも不十分ならシンプレクティックな
   手法へ替えること（第29章 29.3/29.6 節は刻み依存性と適応刻みの限界を固定しているが、
   長期の保証はしない）。
5. **診断量の単位系** — `G = 1`・質量 ≡ `mu` であるため、値そのものは SI ではない
   （第28章）。
6. **外力なし** — 大気抵抗・潮汐力・第三天体による固定場の摂動は与えない
   （必要なら `gravity_model=` で自行実装した場を差し込むことはできる）。
7. **初期速度ガードの無効化** — 全静止の系では速度発散ガードが働かず、
   有限値ガードのみに依存する（第26章）。

### 31. CLI 仕様（多体）

**多体に CLI は存在しない。** `range_calc.py` は弾道（第15章）と軌道（第23章）の
2 モードのみを提供し、`nbody` を import しない。

多体は Python API（`nbody.NBodySimulator`）から呼び出すか、ネイティブ GUI
（`desktop/nbody_app.py`、`desktop/README.md` §3.3）を使う。

---

*最終更新: 多体（第IV部）に任意の適応刻みを追加し、`NBodySimulator(adaptive=)`・
`SystemResult.timestep_min/max`・最短ペア周期の `1/ADAPTIVE_STEPS_PER_PERIOD` 基準を
第26・27・29・30章に追記、テスト数を 200 件（`test_nbody.py` 67 件）へ更新した（2026-10-19）。
前回は「弾道シミュレーション」の単一前提のままだった本書を 4 部構成
（第I部 共通基盤 / 第II部 弾道 / 第III部 軌道 / 第IV部 多体）に再構成した。第19章の軌道要素
に空の見出ししか無く内容が第IV部側に置かれていた配置ミスを修正し、初期条件・数値解法・
検証基準・適用限界・CLI を各モデルごとに分離した。あわせて軌道・多体の検証基準（第21章・
第29章）と適用限界（第22章・第30章）を新規に追加した（2026-10-18）。前回はタイトルと
適用範囲を「弾道シミュレーション」から「弾道・軌道・多体」へ更新し、対象コードに
`orbital.py` / `nbody.py` を追加、テスト数記載を 192 件へ更新した（2026-10-18）。それより前は
摂動モデル（J2 扁平 `j2_gravity()`・合成 `sum_fields()`）と高度依存抗力（`DensityModel` /
`DragModel`、区分指数大気）を追記し、テスト数を 133 に更新した（2026-10-17）。*
