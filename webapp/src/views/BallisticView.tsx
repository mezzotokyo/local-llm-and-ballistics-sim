import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { simulate } from '../api'
import { TrajectoryChart, type ChartView } from '../components/TrajectoryChart'
import {
  buildRequest,
  DRAG_COEFFICIENT_DEFAULT,
  DENSITY_PRESETS,
  DT_MAX,
  DT_MIN,
  dtValidityMessage,
  format,
  INITIAL_BALLISTIC_CONTROLS,
  resultMetrics,
  SPIN_AXIS_MAX,
  SPIN_AXIS_MIN,
  SPIN_RATE_MAX,
  SPIN_RATE_MIN,
  type Controls,
  type DensityModel,
} from '../lib/sim'
import type { SimulateRequest, SimulateResponse } from '../types'

export function BallisticView() {
  const [controls, setControls] = useState<Controls>(INITIAL_BALLISTIC_CONTROLS)
  const [data, setData] = useState<SimulateResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [view, setView] = useState<ChartView>('xy')

  const run = useCallback(async (request: SimulateRequest) => {
    setLoading(true)
    setError(null)
    setData(null)
    try {
      setData(await simulate(request))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void run(buildRequest(INITIAL_BALLISTIC_CONTROLS))
  }, [run])

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void run(buildRequest(controls))
  }

  const patch = (changes: Partial<Controls>) =>
    setControls((current) => ({ ...current, ...changes }))

  const metrics = data ? resultMetrics(data) : null

  return (
    <>
      <div className="layout">
        <form className="panel controls" onSubmit={handleSubmit}>
          <h2>Launch conditions</h2>

          <label className="field">
            <span>
              初速 <b>{format(controls.velocity_kmph, 1)}</b> km/h
            </span>
            <input
              type="range"
              min={10}
              max={500}
              step={1}
              value={controls.velocity_kmph}
              onChange={(event) => patch({ velocity_kmph: Number(event.target.value) })}
            />
          </label>

          <label className="field">
            <span>
              発射角 <b>{format(controls.angle_deg, 1)}</b> deg
            </span>
            <input
              type="range"
              min={1}
              max={89}
              step={1}
              value={controls.angle_deg}
              onChange={(event) => patch({ angle_deg: Number(event.target.value) })}
            />
          </label>

          <label className="field inline">
            <span>抗力係数 Cd</span>
            <span className="read-only">{DRAG_COEFFICIENT_DEFAULT}（球体）</span>
          </label>

          <label className="field inline">
            <span>抗力（密度）モデル</span>
            <select
              value={controls.densityModel}
              onChange={(event) =>
                patch({ densityModel: event.target.value as DensityModel })
              }
            >
              {DENSITY_PRESETS.map((preset) => (
                <option key={preset.value} value={preset.value}>
                  {preset.label}
                </option>
              ))}
            </select>
          </label>

          <fieldset className="spin">
            <legend>スピン（Magnus 揚力）</legend>

            <label className="field">
              <span>
                回転数 <b>{format(controls.spinRate, 0)}</b> rpm
              </span>
              <input
                type="range"
                min={SPIN_RATE_MIN}
                max={SPIN_RATE_MAX}
                step={50}
                value={controls.spinRate}
                onChange={(event) => patch({ spinRate: Number(event.target.value) })}
              />
            </label>

            <label className="field">
              <span>
                スピン軸角 <b>{format(controls.spinAxisDeg, 0)}</b> deg
              </span>
              <input
                type="range"
                min={SPIN_AXIS_MIN}
                max={SPIN_AXIS_MAX}
                step={5}
                value={controls.spinAxisDeg}
                onChange={(event) => patch({ spinAxisDeg: Number(event.target.value) })}
              />
            </label>
          </fieldset>

          <label className="field inline">
            <span>刻み幅 dt (s)</span>
            <input
              type="number"
              min={DT_MIN}
              max={DT_MAX}
              step={DT_MIN}
              value={controls.dt}
              onInvalid={(event) => {
                event.currentTarget.setCustomValidity(
                  dtValidityMessage(event.currentTarget),
                )
                setData(null)
              }}
              onChange={(event) => {
                event.currentTarget.setCustomValidity('')
                patch({ dt: Number(event.target.value) })
              }}
            />
          </label>

          <label className="field checkbox">
            <input
              type="checkbox"
              checked={controls.adaptive}
              onChange={(event) => patch({ adaptive: event.target.checked })}
            />
            <span>adaptive 刻み（安定性上限で自動短縮）</span>
          </label>

          <label className="field inline">
            <span>表示</span>
            <select
              value={view}
              onChange={(event) => setView(event.target.value as ChartView)}
            >
              <option value="xy">断面 (x–y)</option>
              <option value="xz">上面 (x–z)</option>
            </select>
          </label>

          <button type="submit" disabled={loading}>
            {loading ? '計算中...' : 'シミュレーション実行'}
          </button>

          {error && <p className="error">エラー: {error}</p>}
        </form>

        <section className="panel results">
          <h2>Result</h2>
          {!data || !metrics ? (
            <p className="placeholder">
              {loading ? '計算中...' : 'シミュレーションを実行してください。'}
            </p>
          ) : (
            <>
              {data.result.timed_out && (
                <p className="warning">
                  時間上限に達しました。着弾前に計算が終了しています。
                </p>
              )}
              <dl className="metrics">
                {metrics.map((metric) => (
                  <div key={metric.key}>
                    <dt>{metric.label}</dt>
                    <dd>{metric.value}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
        </section>
      </div>

      <section className="panel chart-panel">
        <h2>Trajectory</h2>
        {data ? (
          <TrajectoryChart
            trajectory={data.trajectory}
            idealRange={data.result.ideal_range}
            groundRange={data.result.ground_range}
            centralBody={false}
            view={view}
          />
        ) : (
          <p className="placeholder">軌跡はまだありません。</p>
        )}
      </section>
    </>
  )
}
