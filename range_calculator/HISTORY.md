# バージョン履歴 — 弾道計算ツール（range_calc）

このドキュメントは `range_calculator/` 以下の弾道シミュレーションが V0 から V5 に至るまでの
変更点を記録する。V5 以降の修正は末尾の「V5 以降の変更」に追記する。各版の記述は実測値に基づく。

物理モデルの詳細については [SPEC.md](SPEC.md) を参照。

---

## 全体サマリ

| 版 | 日付 | 行数 | 積分手法 | 構造 | テスト |
|----|------|------|----------|------|--------|
| V0 | 2026-10-01 | 140 | 陽的 Euler（1次） | 単一ファイル、`main` ブロックに I/O | なし |
| V2 | 2026-10-02 | 121 | 陽的 Euler（1次） | 単一ファイル、クラス化 | なし |
| V3 | 2026-10-02 | 148 | RK4（4次） | 単一ファイル、状態ベクトル化 | なし |
| V4 | 2026-10-05 | 81 + 278 + 182 | RK4（4次）固定刻み | 3 モジュール分割 | 54 件 |
| V5 | 2026-10-06 | 123 + 347 + 182 | RK4（4次）+ 適応刻み（任意） | V4 のまま・CLI に上限値とモードを追加（デフォルトは V4 と同一動作） | 82 件 |

  進化の軸:

```
V0 ──── V2 ──── V3 ──── V4 ──── V5
関数    クラス  精度向上  モジュール分割  発散耐性
構成    化      (RK4)     + 設定外部化    (dt を上限化)
                   + テスト
```

V5 は**数値結果を改善していない**。基準シナリオは V4 と完全に同一（101.12 m / 4.37 s）である。


---

## 基準シナリオ（比較の前提）

すべての版の出力比較は `data.csv = 170, 35`（170 km/h, 35°）および `dt = 0.01 s` で実施している。
理想射程はいずれの版でも 213.60 m で一致する（閉形式なので変更影響を受けない）。

---

## V0 — 初期実装（2026-10-01, 140 行）

### 内容

物理計算と I/O が単一ファイルに同居した最初の版。

- `ProjectileConstants` — 物理定数をクラス属性として保持（`MAX_TIME`, `GRAVITY`,
  `AIR_DENSITY`, `MASS`, `DIAMETER`, `DRAG_COEFFICIENT`）
- `calculate_range_ideal(v0_mps, launch_angle_rad)` — 無抗力の閉形式 `v0² sin(2θ) / g`
- `calculate_range_with_drag(initial_velocity_mps, launch_angle_rad)` — Euler 積分による抗力計算
- `__main__` ブロック — `data.csv` 読み取り、単位変換、結果表示

### 出力値

```
Ideal Range (No Drag):    213.60 m
Realistic Range:          100.60 m
Actual Flight Time:         4.36 s
```

### 限界

- **積分精度が 1 次**。Euler 法は局所誤差 `O(dt²)` であり、`dt = 0.01` では抗力積分分が過大評価される。
- **物理定数がコードに埋め込み**。変更にはソース編集が必要。
- **エラー処理が限定的**。`FileNotFoundError` と汎用の `Exception` を別々に捕まえるのみで、
  値の妥当性検証が一切ない。
- **物理定数のコメントが自己申告**（`# Corresponds to 149g`）だが、`Cd = 0.47` の出典が不明。

### 収束性の実測（V0 の Euler 実装）

| `dt` | 射程 | 飛行時間 |
|------|------|----------|
| 0.01 | 100.6027 m | 4.3600 s |
| 0.001 | 101.0697 m | 4.3720 s |
| 0.0001 | 101.1164 m | 4.3737 s |

`dt` を 1/100 にすると約 0.51 m 伸びている一方、`1/10` にすると約 0.47 m 伸びている。
誤差が `dt` に比例して縮むため、**1次収束**が確認できる。極限値は 101.12 m 付近。

---

## V2 — クラス化（2026-10-02, 121 行）

### 変更点

- `calculate_range_with_drag()` 関数を `ProjectileSimulator` クラスに変換。
  状態（`vx`, `vy`, `x`, `y`, `t`）がインスタンス変数になり、理想計算と抗力計算を
  同じクラスの 2 メソッドとして提供。
- `dt` を `run_simulation(dt=0.01)` の引数に変更（V0 は関数内でハードコード）。
- `constants` を辞書（`{'drag_scaling_factor': ...}`）として注入する形に変更。
- `__main__` ブロックの変数を大文字（`V0_KMPH`, `ANGLE_DEG`）に変更。
- 読み取り失敗時のフォールバック値を `150.0, 40.0` から `170.0, 35.0` に変更。

### 出力値

```
Ideal Range (No Drag):    213.60 m
Realistic Range:          100.60 m
Actual Flight Time:         4.36 s
```

**V0 と完全に同一**。これは意図された設計上の選択であり、クラス化のみでは数値が改善しないことを示す。

### 限界

- 積分手法は 1 次のまま。数値的な利得はゼロ。
- 物理定数は依然としてクラス属性にハードコード。
- 理想計算と抗力計算で `ProjectileSimulator` を 2 インスタンス生成しており、冗長。

---

## V3 — RK4 導入（2026-10-02, 148 行）

### 変更点

- **積分手法を Euler（1次）から RK4（4次）へ変更**。これが本版の中核。
- 状態をスカラー 4 変数からタプル `state = (x, y, vx, vy)` へ統一。
- `derivatives(state, constants)` 関数を新設。ODE の右辺を独立させ、RK4 の各ステージで再利用する形に。
- 着弾処理を単純化し、`y < 0` になった時点で `y = 0` にスナップ（V0/V2 の線形補間を**削除**）。
- 出力ヘッダを `--- Simulation Results (RK4 Refactored) ---` に変更。

### 出力値

```
Ideal Range (No Drag):    213.60 m
Realistic Range (RK4):    101.21 m
Actual Flight Time:         4.39 s
```

### 数値評価

V0/V2 の 100.60 m から 101.21 m へ 0.61 m 改善（+0.61 %）。Euler の 1 次誤差が解消した。

ただし **V3 は正確ではない**。コード中のコメント自身がこれを認めており、
着弾時の `x` 補正を行わないため、最終ステップの分だけ過大評価になる。

収束性の実測（V3 実装のまま）:

| `dt` | 射程 | 飛行時間 |
|------|------|----------|
| 0.01 | 101.2105 m | 4.3900 s |
| 0.001 | 101.1234 m | 4.3750 s |
| 0.0001 | 101.1215 m | 4.3740 s |

極限値 101.1215 m に対し、`dt = 0.01` で 0.089 m の誤差。`dt` を 1/10 にすると誤差が約 1/9
となり、**4次収束**が確認できる。

### 限界

- 着弾補間の欠如により、`dt = 0.01` の基準シナリオで 0.089 m の系統誤差。
- 物理定数は依然としてハードコード。
- 時刻管理がループ先頭で `self.t += dt` されており、打ち切り判定と積分の順序が V0/V2 と異なる。
- テストが存在しない。

---

## V4 — モジュラー分割と検証体制（2026-10-05, 81 + 278 + 182 行）

### 変更点

V4 はコードの見た目（81 行）よりも、**責務の分割**が主要変更である。

| ファイル | 行数 | 責務 |
|----------|------|------|
| `physics_config.py` | 182 | 物理パラメータの保持・検証・外部設定の読み込み |
| `ballistics.py` | 278 | 純物理（RK4 積分）。**ファイル I/O を一切行わない** |
| `range_calc_v4.py` | 81 | CLI エントリポイント。入力解析・単位変換・表示のみ |

#### 1. 物理定数の外部化

`ProjectileConstants` のクラス属性を `frozen=True` の `PhysicalParameters` dataclass に置換。
値は `config/physics_constants.json` から読み込む。

```json
{"max_time": 300.0, "gravity": 9.81, "air_density": 1.225,
 "mass": 0.149, "diameter": 0.075, "drag_coefficient": 0.47}
```

- 制約をフィールドごとに分類（`PositiveFields` / `NonNegativeFields`）し、`__post_init__` で検証
- 未知のキーは `ValueError`（黙って無視しない）
- 設定ファイル不在時は警告とともに組み込み既定値へ退避（ツールは設定と独立に動作する）
- `ProjectileConstants` は後方互換のビューとして残置。新規コードは `PhysicalParameters` を使うこと

#### 2. 着弾補間の再実装（V3 からの修正）

V3 で削除されていた `y = 0` 交点の線形補間を `ballistics.py` に再実装。
さらに `ratio` を `[0, 1]` にクランプし、`span = 0` の退化ケースを明示的に扱った。

この 1 点が V3 と V4 の数値差（101.21 m → 101.12 m）の全量である。

#### 3. 数値ガードの追加（新規）

V0〜V3 に存在しなかった防御機構:

| ガード | 条件 | 挙動 |
|--------|------|------|
| 安定性警告 | `dt > 0.5 / (k·v)` | `RuntimeWarning` を発して続行 |
| 非有限値検出 | 状態に `NaN`/`Inf` | `SimulationDiverged` |
| 速度異常検出 | `v > max(v0 × 1000, g × max_time)` | `SimulationDiverged` |
| 粗すぎる刻み検出 | 上昇中発射が 1 ステップ目で着弾 | `ValueError`（推奨 `dt` を提示） |
| 引数検証 | 非有限・非正・型違い | `TypeError` / `ValueError` |

いずれも閾値と理由をメッセージに含めるため、発生時に原因が特定できる。

#### 4. 戻り値の拡充

`FlightResult` NamedTuple を新設し、`run_simulation()` の 2 値返りから 5 情報を公開:

```
ground_range, flight_time, impact_speed, landed, timed_out
```

#### 5. 冪等性と再開

`run_simulation()` は `resume=False` の限り `reset()` を先に呼ぶため、
繰り返し呼んでも同一結果になる。`reset()` は一時的な刻み幅の上書きも破棄する。
`resume=True` で中断点から継続でき、着弾済みの場合は no-op。

#### 6. テスト体制の確立（新規）

`test_range_calc_v4.py`（437 行、54 件 / 9 系統）を新設。
V0〜V3 には 1 件も存在しなかった。

| 系統 | 件数 | 内容 |
|------|------|------|
| `AnalyticAgreementTests` | 3 | `k=0` で射程・飛行時間が閉形式と一致 |
| `ConvergenceTests` | 2 | 着弾補間により `dt` に依存しない |
| `LandingStateTests` | 5 | 着弾状態の物理的整合性（水平発射・負角を含む） |
| `PhysicsTests` | 2 | 抗力による射程短縮と、最佳角度が 45° 未満になること |
| `RegressionTests` | 2 | 基準シナリオ 101.12 m・4.37 s の固定 |
| `SimulatorContractTests` | 10 | 冪等性・`reset`/`resume`・引数検証・コアの I/O 禁止 |
| `ConfigurationTests` | 12 | パラメータ検証・未知キー・レガシー互換 |
| `ScenarioLoadingTests` | 5 | `data.csv` 異常時の退避、CLI 実行 |
| `NumericalGuardTests` | 13 | 発散検出・安定性警告・粗すぎる刻み |
| **合計** | **54** | |

うち `SimulatorContractTests` の 1 件は `ballistics` モジュールがファイル I/O を
行わないことを実際に検証する（設計上の境界をテストで固定している）。

### 出力値

```
Ideal Range (No Drag):    213.60 m
Realistic Range (RK4):    101.12 m
Actual Flight Time:         4.37 s
```

---

## V5 — 適応刻み（発散耐性、精度改善ではない）（2026-10-06, 123 + 347 + 182 行）

### 変更点

V5 は `dt` のセマンティクスを「固定刻み」から「**刻み幅の上限（ceiling）**」に変更し、
`adaptive=True` のとき各ステップを RK4 の安定性帯内に収まるまで自動的に短縮する。
モジュール分割・設定外部化・物理モデルは V4 のまま変更していない。

| ファイル | 行数 | 変更 |
|----------|------|------|
| `ballistics.py` | 278 → 347 | `_next_timestep()`、`adaptive` フラグ、ステップ計数 |
| `range_calc_v4.py` | 81 → 123 | `parse_args()`、`--adaptive`、`dt_max` 位置引数 |
| `physics_config.py` | 182 | 変更なし |
| `test_adaptive_timestep.py` | 268（新規） | 28 件 / 7 系統 |

#### 1. 刻み計算の式

```
h = min( dt_max, STABILITY_LIMIT / (k · |v_now|) )
```

`_stable_timestep()` を**発射時速度ではなく現在速度**に対して評価するのが変更点である。
抗力で減速するにつれ `h` の上限は緩むため、同一の `dt_max` でも刻みは一様にならない。

`h` は `dt_max` を超えない。**縮小のみで、延長はしない。**

#### 2. 観測値の公開

`FlightResult` に `steps` / `timestep_min` / `timestep_max` を追加し、
CLI にも `Integration Steps` と `Shortest Step Taken` を表示した。
刻みが実際に縮んだ与否を出さないと、本変更の影響を検証できないため。

#### 3. CLI

```
python range_calc_v4.py [scenario_path] [dt_max] [--adaptive]
```

`dt_max` を省略した場合は 0.01 s。`--adaptive` なしの場合の挙動は V4 と完全に同一である。
なお、この時点でファイル名は `range_calc_v4.py` であったが、後日 `range_calc.py` に改称された
（末尾の「V5 以降の変更」に記載の「CLI ファイル名の改称」を参照）。
現行 CLI に `range_calc_v4.py` という名称のファイルはないが、当時のスナップショットが
`range_calculator/archive/range_calc_v4.py` に参照用として復元されている。

### 出力値（基準シナリオ）

```
--- Simulation Results (RK4 Refactored) ---
Input Velocity: 170.0 km/h
Launch Angle: 35.0 deg
Timestep Ceiling: 0.01 s

--- Range Comparison ---
Ideal Range (No Drag): 213.60 m
Realistic Range (RK4, With Drag): 101.12 m
Actual Flight Time: 4.37 s
Integration Steps: 438
```

**V4 と同一。** 基準シナリオでは `dt_max = 0.01` が既に安定性帯の内側にあるため、
刻みは 1 度も短縮されない。

### 数値実測（固定刻み vs 適応刻み）

基準シナリオの安定性上限は `dt_stable = 1.2405 s`（`k = 8.536e-3`, `v₀ = 47.222 m/s`）。
極限値（`dt = 1e-4`）は **101.1215 m**。

| `dt_max` | 固定刻み | 適応刻み | 適応 ステップ数 | `h_min` | `h_max` |
|----------|----------|----------|----------------|---------|---------|
| 0.01 | 101.1214 m | 101.1214 m | 438 | 0.01000 | 0.01000 |
| 0.05 | 101.1192 m | 101.1192 m | 88 | 0.05000 | 0.05000 |
| 0.20 | 101.1035 m | 101.1035 m | 22 | 0.20000 | 0.20000 |
| 0.62 | 101.0384 m | 101.0384 m | 8 | 0.62000 | 0.62000 |
| 1.00 | 100.1401 m | 100.1401 m | 5 | 1.00000 | 1.00000 |
| 1.24 | 99.2622 m | 99.2622 m | 4 | 1.24000 | 1.24000 |
| 5.00 | **`ValueError`** | 94.6735 m | 3 | 1.24049 | 2.76402 |
| 50.0 | **`SimulationDiverged`** | 94.6735 m | 3 | 1.24049 | 2.76402 |

2 つの事実が読み取れる。

1. **`dt_max ≤ dt_stable` の範囲では固定刻みと完全に一致する**（`assertEqual` で検証）。
   適応刻みは「何もしない」のではなく、「必要なときしか縮めない」実装である。
2. **`dt_max > dt_stable` で初めて差が出る**。固定刻みは発散または例外で止まるが、
   適応刻みは短縮して完走する。ただし 94.67 m は誤差 **−6.4 m** であり、
   V0 の 1 次 Euler（−0.52 m）より悪い。

### 適応刻みは精度を改善しない（実測に基づく）

当初、`h` に対し「着弾分解能」の上限も併せようとした:

```
h <= LANDING_RESOLUTION · y / (−v_y)      # LANDING_RESOLUTION = 0.5
```

**これは無限ループを引き起こすため採用しなかった。** 1 ステップで消費できる残存高さを
50% に制限するため `y` は幾何級数的に 0 へ収束し、**地面を跨ぐこと自体ができなくなる**。
着弾判定は `y < 0.0` という厳密な不等号なので発火せず、積分が終了しない。
実測（`dt_max = 5`、8 ステップ目まで）:

```
h=0.01955860  y=0.35909041
h=0.00968500  y=0.17926055
h=0.00481955  y=0.08955994
h=0.00240411  y=0.04476249
h=0.00120065  y=0.02237689
```

`y` も `h` も毎ステップ半分になり、`y = 0` に漸近するだけで符号が変わらない。
`c = 1` としても着弾点上の中間状態になるため，同様に終了しない。
この上限は選択した基準（安定性バンド）にも外れており、V4 の着弾補間が既に
交差点を解決済みである。削除した経緯は `_next_timestep()` の docstring に残した。

### 限界

- **精度保証ではない。** 誤差はおおむね `dt_max` に比例して縮む。
  適応刻みは発散を防ぐに過ぎず、刻みを限界いっぱいまで拡大すれば
  誤差はむしろ拡大する（`dt_max = 1.24` で −1.86 m、V0 の Euler より悪い）。
- **`k = 0` では安定性帯が存在しない**ため縮小が起きず、粗い `dt_max` は
  初回着弾判定の `ValueError` に至る。この挙動は意図的に維持している。
- **`h` の安定性上限は現在速度で評価する**ため、減速中のステップは
  発射時速度由来の `dt_stable` を超える値になりうる。実測で 2.76402 s
  （`dt_max = 5` の場合）。速度が減少している物理状態なので理論上は正当だが、
  「全ステップが `dt_stable` 以下」という誤解を招くため docstring に明記した。


---

## 出力値の変遷

| 版 | 理想射程 | 実射程 | 飛行時間 | 対 V0 の誤差 |
|----|----------|--------|----------|--------------|
| V0 | 213.60 m | 100.60 m | 4.36 s | — |
| V2 | 213.60 m | 100.60 m | 4.36 s | 0.00 m |
| V3 | 213.60 m | 101.21 m | 4.39 s | +0.61 m |
| V4 | 213.60 m | 101.12 m | 4.37 s | +0.52 m |
| V5 | 213.60 m | 101.12 m | 4.37 s | +0.52 m |

V5 は基準シナリオで V4 と同一の値を出力する。差は 0.00 m。
`--adaptive` を付けても `dt_max = 0.01` では刻みが短縮されないため当然である。

出力は小数第 2 位まで。内部実値は順に 100.6027 / 100.6027 / 101.2105 / 101.1214 / 101.1214 m。

RK4 の積分誤差の極限値は **101.1215 m**（着弾補間あり、`dt → 0`）。
**V4 は `dt = 0.01` で 101.1214 m を出力し、極限値との差は 0.0001 m。**
着弾補間が効いているため、`dt` を 1/10 にしても結果はほとんど変わらない。

### 各版と極限値との差

| 版 | 出力 | 極限値との差 |
|----|------|--------------|
| V0/V2（Euler, `dt=0.01`） | 100.6027 m | 0.519 m |
| V3（RK4, 着弾スナップ） | 101.2105 m | 0.089 m |
| V4（RK4, 着弾補間） | 101.1214 m | 0.0001 m |
| V5（適応刻み, `dt_max=0.01`） | 101.1214 m | 0.0001 m |

`V3` と `V4` の差は積分精度ではなく**着弾処理の実装1点**に由来する。
極限値 101.1215 m は着弾補間を有効にした場合のみ到達するため、
V3 が 101.21 m を出力していたのは RK4 が高精度であるにもかかわらず、
着弾スナップが最終ステップの誤差を取り込んでいたためである。

---

## 設計判断の変遷

### V0 → V2: 構造的投資

数値上の結果は変わらず、`ProjectileSimulator` へのクラス化という純粋な構造改善。
**リファクタリングは挙動を変えないことを示す事例**として位置づけられる。

### V2 → V3: 精度への投資

Euler（1次）から RK4（4次）への変更は最短経路で精度を改善した（誤差 0.519 m → 0.089 m）。
ただし着弾処理をスナップに単純化した副作用が伴い、V3 は「高精度の解法に見合う精度」
に到達せず、過信できない状態を生んだ。

### V3 → V4: 境界の明確化と検証

最も大きな変化はコードの増分ではなく、
**「どの処理が副作用を持つか」の分離**にある。

| 版 | 物理計算 | I/O | 設定 |
|----|----------|-----|------|
| V0 | 関数 | `__main__` に混在 | コード内ハードコード |
| V2 | メソッド | `__main__` に混在 | コード内ハードコード |
| V3 | メソッド + 関数 | `__main__` に混在 | コード内ハードコード |
| V4 | `ballistics` のみ | `range_calc_v4` のみ | `physics_config` + JSON |

この分離により、`ballistics` はファイル I/O なしで直接テスト可能になった
（`test_core_module_performs_no_file_io` が保証）。

### V4 → V5: 保証しないことを明示する

V5 は数値を改善していない。追加したのは**発散を起こさないこと**であり、
同時に**それが精度の保証にならないこと**の明示でもある。

この移動で評価すべきではない点:

- 基準シナリオの出力は V4 と同一（101.1214 m）。改善ではない。
- `dt_max` が安定性帯内であれば、固定刻みとの差分は**厳密にゼロ**。
  適応刻みは「既存の刻みを置き換える」のではなく「必要なときだけ縮める」実装である。

この移動で評価すべき点:

- 固定刻みが `ValueError` / `SimulationDiverged` で停止していた入力
  （`dt_max ≥ 5`、`mass = 1e-12`、10 万 km/h 級の発射）が完走する。
- `FlightResult` が刻みの実効幅を公開するため、**刻みが縮んだ事実が検証可能**になった。

これは V0 → V2 と同型の「構造投資」であり、精度投資（V2 → V3）ではない。
V4 が「発散防止であって精度保証ではない」と docstring に書いていた結論を、
コードとテストの両方で固定し直したものである。

---

## 残存課題（V5時点）

1. **`Cd = 0.47` の出典が未確定**。質量 149 g・直径 75 mm は野球ボール相当だが、
   野球ボールの実測 `Cd` は自由飛行でおおむね 0.33–0.36、風洞実験では球種により 0.3 前後
   まで低下する（例: NPB）。どの球種を想定した値かの出典が要調査。
   なおこの値は V0 から V5 まで一度も変更されておらず、現行 JSON にもそのまま継承されている。
   **未着手。**
 2. ~~**固定刻み幅**~~ → **V5 で適応刻みを任意のモードとして追加**。
    ただし残存している問題: **適応刻みは精度を改善しない**。刻みを上限いっぱいまで
    拡大すれば誤差は拡大する。真に精度を改善する適応制御には局所誤差推定
    （step doubling、RK45 など）が必要で、これは未実施。
    安定性上限は**現在速度**で評価しているため、減速する飛行後半では緩やかに緩む。
 3. **`ProjectileConstants` の後方互換層**が残置されている。移行完了後は削除の余地がある（優先度：低）。
    **未着手。**
 4. ~~**V0〜V3 のファイルが削除されていない**~~ → **`range_calculator/archive/` へ集約して解決済み**。
    履歴としての参照価値は残るが `range_calc_v*.py` という命名が現行版と紛らわしいため、
    V0〜V3 の単一ファイル版（`range_calc_v0.py` / `range_calc_v2.py` / `range_calc_v3.py`）を
    `range_calculator/archive/` へ移動した。改称で現行 CLI に吸収されていた V4 も、
    当時のスナップショット（baseline `31e6f18` の `range_calc_v4.py`）を同ディレクトリへ復元した。
    詳細は「V5 以降の変更」の該当項を参照。CLI 名については課題 5 で解決済み。
 5. ~~**CLI のファイル名に "v4" が残っている**~~ → **`range_calc.py` に改称して解決済み**。
    コミット `430c71e` で `range_calc_v4.py` → `range_calc.py` へ改称し、テストの import 参照を更新した。
    その後の SPEC.md および CLI docstring の参照漏れも修正済み。課題 4 のうち CLI 命名については本件で対応済み。

---

## V5 で導入したテスト（28 件 / 7 系統）

`test_adaptive_timestep.py`（268 行）。V4 の 54 件は**無改変で通過**している。
合計 82 件。

| 系統 | 件数 | 内容 |
|------|------|------|
| `TimestepCeilingTests` | 4 | 刻みが `dt_max` を超えないこと、縮む局面があること |
| `AgreementWithFixedTimestepTests` | 2 | 安定性帯内では固定刻みと `assertEqual` で一致 |
| `StabilityAbsorptionTests` | 5 | 粗い `dt`・異常抗力・超高速発射の完走、警告ゼロ |
| `NoAccuracyClaimTests` | 3 | **粗い上限でも誤差が残る**ことを固定（精度改善を主張しない） |
| `LifecycleTests` | 5 | 冪等性、`reset` / `resume`、カウンタ、引数検証 |
| `EdgeCaseTests` | 4 | 角度 0/90/180/−45、`v₀ = 0`、`k = 0` での初回着弾判定 |
| `CommandLineTests` | 5 | `parse_args`、`--adaptive`、出力表示 |
| **合計** | **28** | |

うち `NoAccuracyClaimTests` は意図的に**適応刻みの限界を固定する**テストである。
「適応化したので精度が上がった」という誤解が将来このリポジトリに持ち込まれた場合、
このテストが失敗する。

---

## V5 以降の変更（2026-10-08）

版番号を振っていない V5 以降の変更。仕様の詳細は [SPEC.md](SPEC.md) を参照。

1. **CLI ファイル名の改称** — `range_calc_v4.py` → `range_calc.py`（`430c71e`）。
   V5 時点まで残っていた残存課題 5 が解決。SPEC.md・CLI docstring の更新漏れも修正した
   （SPEC 冒頭の「v5 時点でも維持されている」という記載は改称経緯の説明に書き換え）。
2. **文字混入検査の強化** — SPEC.md L20 に混入していた「規則」の簡体字表記を正しい字体に修正し、
   `tools/check_text_hygiene.py` の `SIMPLIFIED_ONLY` に検出漏れていた該当文字を追加した。
3. **発射条件の CLI 上書き** — `--v0=<km/h>` / `--angle=<deg>`（`=` 書式のみ）を追加。
   フィールド単位の独立フォールバック（引数 → `data.csv` → 既定値）で、
   両方指定した場合は `data.csv` を読まない。不正値・`=` なし・重複指定は `SystemExit` で拒否。
   テストは `CommandLineTests` に 7 件を追加し、**合計 82 件 → 89 件**となった。
4. **旧版ファイルのアーカイブ** — V0〜V3 の単一ファイル版
   （`range_calc_v0.py` / `range_calc_v2.py` / `range_calc_v3.py`）を `range_calculator/archive/` へ移動。
   残存課題 4 を解決。改称（`430c71e`）で現行 CLI に吸収されていた V4 も、
   当時のスナップショット（baseline `31e6f18` の `range_calc_v4.py`、82 行）を同ディレクトリへ復元した。
   これらは**参照専用のアーカイブ**であり、実行時の動作は保証しない
   （当時の `ballistics` / `physics_config` を前提とし、`data.csv` も同階層には存在しない）。
   現行版・テスト（89 件）への影響はない。

---

## V5 以降の変更（2026-10-17）

1. **状態ベクトルの 3D 化** — `State` を `(x, y, z, vx, vy, vz)` の 6 元組に拡張し、
   名前付きインデックス定数 `X, Y, Z, VX, VY, VZ = range(6)` を導入した。重力は鉛直方向
   成分 `vy` を更新する。`desktop` / `webapp` の記録コールバックと `test_range_calc.py` を
   6 要素に対応させた。`z` は現状常に 0（横方向の将来拡張用）。
2. **ニュートン球面重力モデル** — 加速度場を `GravityModel = Callable[[State], tuple[float, float, float]]`
   として差し替え可能にした（`constant_gravity()` 既定、`newtonian_gravity(mu)` は
   `a = -mu·r/|r|³`）。`ProjectileSimulator` に `gravity_model` / `ground_collision` と
   全状態指定の `from_state()` を追加。標準重力パラメータ `mu`（既定: 地球 3.986004418e14）
   を `physics_config` / `config/physics_constants.json` に追加した。
3. **軌道要素と CLI・API への接続** — `orbital.py` に `orbital_elements()`（比エネルギー・
   長半径・離心率・近点/遠点・周期・傾斜角）を追加。CLI に `--orbital` / `--radius=<m>`
   モードを追加し（`parse_args()` の返り値を `CliArgs` に変更）、webapp API に
   `gravity_model`（`"constant"` / `"newtonian"`）と `initial_state`、`orbital` 出力を、
    desktop の `LaunchConditions` / `SimulationOutcome` に同項目を追加した。UI ウィジェットは
    この時点では変更していない（CLI とモデル/API 層のみ。GUI 対応は後述の 5.）。
4. **摂動モデル（J2・大気・多体合成）** — 重力・抗力をそれぞれ加速度場
   `GravityModel` / `DragModel` として差し替えられるよう一般化した。`j2_gravity(mu, j2, R)`
   は点質量に第2帯球（扁平）項を加え（極軸は `z`、`j2 = 0` で厳密に `newtonian_gravity` と
   一致）、`sum_fields(*fields)` は任意個の場を成分加算して多体問題へ拡張する合成フックを
   与える。大気は `DensityModel = Callable[[float], float]` を導入し、`constant_density` /
   `exponential_density` / `tabulated_density`（区分指数。`EARTH_ATMOSPHERE_LAYERS` は
   0–1000 km テーブル）と、高度取得 `orbital_altitude(R)` / `flat_altitude()` を用意した。
   積分は `derivatives_with_models(state, gravity, drag=None)` に一般化し、
   `ProjectileSimulator` は keyword-only の `drag_model` を受ける（既定は従来の一定抗力で
   数値完全一致）。パラメータ `j2` / `equatorial_radius` / `scale_height` /
   `sea_level_density` を JSON に追加、CLI に `--j2` / `--atmosphere`、webapp API に
   `gravity_model="j2"` と `drag_model`（`"constant"` / `"exponential"` / `"tabulated"`）、
    desktop の `LaunchConditions` に `drag_model` / `j2` を追加した。UI ウィジェットは
    この時点では変更していない（GUI 対応は後述の 5.）。

5. **GUI/UI の適合** — `desktop` と `webapp` の UI を拡張モデルへ追随させた。両者とも
   重力モデル（一定 / ニュートン / J2）と抗力（密度）モデル（なし / 一様 / 指数 / 区分指数）の
   セレクタ、中心重力時の軌道初期状態（半径・速度。円軌道速度を自動設定）入力を追加し、
   Result は弾道（射程系）と軌道（軌道要素系）で行を動的に切り替える。`desktop` では
   これらを `gui_model` の純関数（`gravity_label` / `density_label` / `orbital_speed` /
   `make_conditions` / `format_optional` / `result_metrics`、`DEFAULT_METRIC_ROWS`）に
   分離し、GUI 層（当時は `app.py`）はウィジェットの接続に徹する。`trajectory_chart.py` は
   `chart_domain` / `axis_ticks` を追加して軌道（負座標・原点＝中心天体、`ideal_range`
   なし）に対応し、`tests/test_trajectory_chart.py` で検証する。`webapp` は `types.ts`
   （`ideal_range: number | null`、`orbital`、`gravity_model` / `drag_model` /
   `initial_state`）、`TrajectoryChart.tsx`（汎用ドメイン・中心天体マーカー）、
   `App.tsx`（同セレクタ・軌道入力・動的 Result）を更新した。重力を中心重力へ切り替えると
   抗力モデルを「なし」へ自動変更する（抗力下の軌道は発散しやすいため）。UI は独立実装だが、
   `desktop/tests/test_agreement.py` が `DRAG_PRESETS` の同期を引き続き検査する。閉軌道では
   **1周期**（周期 × 1.05）を自動積分して軌道を閉じ（`desktop/gui_model.orbital_time_span`、
   `server.ORBITAL_PERIOD_MARGIN`）、刻み幅を周期 / 4000 に丸める（既定 `dt=0.01` では 1周に
   約60万ステップ・約30秒かかるため）。着弾が無い軌道では時間上限警告を抑止する。

6. **Magnus 揚力（スピン）** — `ballistics` に `magnus_lift(parameters, spin_rpm,
   spin_axis_deg)` と `spin_axis_vector(θ)`、定数 `LIFT_COEFFICIENT_SLOPE=1.0` /
   `LIFT_COEFFICIENT_MAX=0.3` を追加した。揚力係数 `C_L = min(slope·S, max)`
   （`S = |ω|R/v`、`R = 直径/2`、`ω = rpm·2π/60`）、加速度
   `a = (1/2·ρ·A·C_L/m)·v·(ŝ×v)`。回転軸 `ŝ = spin_axis_vector(θ)` は
   `θ=0` でバックスピン（上向き）、`+90` で *+z*、`-90` で *-z*、`±180` でトップスピン。
   積分は `derivatives_with_models(..., lift=)` / `_rk4_step(..., lift=)`、
   `ProjectileSimulator(lift_model=)` / `from_state(..., lift_model=)` を通し、
   `FlightResult.lateral_range`（`|z|`）を出力する。CLI に `--spin=<rpm>` /
   `--spin-axis=<deg>`（`CliArgs.spin_rpm` / `spin_axis_deg`）と横ずれ表示を追加した。
   webapp API は `spin_rate` / `spin_axis_angle`（既定 0）を受け、軌跡に `z`、
   Result に `lateral_range` を返す。desktop / webapp の UI にスピン入力と横ずれ行を
   追加し、チャートに上面（x–z）ビューを追加した。
7. **desktop の画面分離** — 単一の `app.py` を廃止し、共有基盤 `app_common.BaseApp`
   と 2 つの独立ウィンドウ `ballistic_app.py`（弾道・スピン・表示切替つき）/
   `orbital_app.py`（中心重力）へ分割した。`build.py` は 2 実行ファイル
   （`range_calculator_ballistic` / `range_calculator_orbital`）を生成する。
8. **webapp の画面分離** — `App.tsx` を上部ナビ（弾道 / 軌道）のシェルとし、
   共通の `lib/sim.ts`（定数・リクエスト生成・メトリクス整形）と
   `views/BallisticView.tsx` / `views/OrbitalView.tsx` に分割した。
   `TrajectoryChart` は `view`（`'xy'` / `'xz'`）で断面・上面を切り替える。
9. **抗力係数 `Cd` の固定** — MLB / NPB の球種プリセットによるプルダウンを廃止し、
   既定プロファイルの球体代表値 `Cd = 0.47` に固定した。`desktop/gui_model.DRAG_PRESETS`
   と `webapp/src/lib/sim.ts` の `DRAG_PRESETS` は既定値の同期検査用に 1 要素のみ保持する。

`range_calculator` のテストは **89 件 → 110 件**（`test_orbital.py` 18 件と
`test_adaptive_timestep.py` の CLI テスト追加分を含む）、さらに摂動モデル追加で
**110 件 → 129 件**、Magnus 追加を含め **133 件**（`test_range_calc.py` に
`MagnusLiftTests` を追加）。`desktop` は 25 件 → 29 件 → 34 件 → **52 件**、スピン・
上面図・画面分離のテストを加え **62 件**（`test_gui_model.py` / `test_trajectory_chart.py` /
`test_agreement.py`）、webapp/server は 7 件 → 12 件 → **17 件**。

---

*最終更新: Magnus 揚力・弾道/軌道の画面分離・抗力係数 `Cd` の球体固定（2026-10-17）*
