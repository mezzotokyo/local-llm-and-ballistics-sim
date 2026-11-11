import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { simulate } from '../api'
import { TrajectoryChart } from '../components/TrajectoryChart'
import {
  buildRequest,
  circularSpeed,
  DRAG_COEFFICIENT_DEFAULT,
  DENSITY_PRESETS,
  DT_MAX,
  DT_MIN,
  dtValidityMessage,
  INITIAL_ORBITAL_CONTROLS,
  ORBITAL_GRAVITY_PRESETS,
  ORBITAL_SPEED_MAX,
  ORBITAL_SPEED_MIN,
  RADIUS_MAX,
  RADIUS_MIN,
  resultMetrics,
  type Controls,
  type DensityModel,
} from '../lib/sim'
import type { GravityModel, SimulateRequest, SimulateResponse } from '../types'

export function OrbitalView() {
  const [controls, setControls] = useState<Controls>(INITIAL_ORBITAL_CONTROLS)
  const [data, setData] = useState<SimulateResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

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
    void run(buildRequest(INITIAL_ORBITAL_CONTROLS))
  }, [run])

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void run(buildRequest(controls))
  }

  const patch = (changes: Partial<Controls>) =>
    setControls((current) => ({ ...current, ...changes }))

  const selectRadius = (radius: number) => {
    patch({
      radius,
      speed: controls.autoSpeed ? circularSpeed(radius) : controls.speed,
    })
  }

  const selectAutoSpeed = (autoSpeed: boolean) => {
    patch({
      autoSpeed,
      speed: autoSpeed ? circularSpeed(controls.radius) : controls.speed,
    })
  }

  const metrics = data ? resultMetrics(data) : null

  return (
    <>
      <div className="layout">
        <form className="panel controls" onSubmit={handleSubmit}>
          <h2>Orbital conditions</h2>

          <label className="field inline">
            <span>重力モデル</span>
            <select
              value={controls.gravityModel}
              onChange={(event) => patch({ gravityModel: event.target.value as GravityModel })}
            >
              {ORBITAL_GRAVITY_PRESETS.map((preset) => (
                <option key={preset.value} value={preset.value}>
                  {preset.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>
              軌道半径 r <b>{(controls.radius / 1000).toFixed(0)}</b> km
            </span>
            <input
              type="range"
              min={RADIUS_MIN}
              max={RADIUS_MAX}
              step={50000}
              value={controls.radius}
              onChange={(event) => selectRadius(Number(event.target.value))}
            />
          </label>

          <label className="field checkbox">
            <input
              type="checkbox"
              checked={controls.autoSpeed}
              onChange={(event) => selectAutoSpeed(event.target.checked)}
            />
            <span>円軌道速度を自動設定</span>
          </label>

          <label className={`field${controls.autoSpeed ? ' disabled' : ''}`}>
            <span>
              軌道速度 v <b>{controls.speed.toFixed(0)}</b> m/s
            </span>
            <input
              type="range"
              min={ORBITAL_SPEED_MIN}
              max={ORBITAL_SPEED_MAX}
              step={10}
              disabled={controls.autoSpeed}
              value={controls.speed}
              onChange={(event) => patch({ speed: Number(event.target.value) })}
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
            <dl className="metrics">
              {metrics.map((metric) => (
                <div key={metric.key}>
                  <dt>{metric.label}</dt>
                  <dd>{metric.value}</dd>
                </div>
              ))}
            </dl>
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
            centralBody={data.orbital !== null}
          />
        ) : (
          <p className="placeholder">軌跡はまだありません。</p>
        )}
      </section>
    </>
  )
}
