import type { GravityModel, SimulateRequest, SimulateResponse } from '../types'

export type DensityModel = (typeof DENSITY_PRESETS)[number]['value']

export const DRAG_COEFFICIENT_DEFAULT = 0.47
export const DRAG_PRESETS = [
  { value: DRAG_COEFFICIENT_DEFAULT, label: '球体（既定値）' },
] as const

export const GRAVITY_PRESETS = [
  { value: 'constant', label: '一定（地表弾道）' },
  { value: 'newtonian', label: 'ニュートン（軌道）' },
  { value: 'j2', label: 'ニュートン+J2（軌道）' },
] as const

export const ORBITAL_GRAVITY_PRESETS = GRAVITY_PRESETS.filter(
  (preset) => preset.value !== 'constant',
)

export const DENSITY_PRESETS = [
  { value: 'none', label: 'なし' },
  { value: 'constant', label: '一様（既定）' },
  { value: 'exponential', label: '指数（高度依存）' },
  { value: 'tabulated', label: '区分指数（0–1000 km）' },
] as const

export const MU = 3.986004418e14
export const DEFAULT_ORBITAL_RADIUS = 7.0e6
export const RADIUS_MIN = 6.5e6
export const RADIUS_MAX = 4.2e7
export const ORBITAL_SPEED_MIN = 100
export const ORBITAL_SPEED_MAX = 12000

export const DT_MIN = 0.0001
export const DT_MAX = 10

export const SPIN_RATE_MIN = 0
export const SPIN_RATE_MAX = 6000
export const SPIN_AXIS_MIN = -180
export const SPIN_AXIS_MAX = 180
export const DEFAULT_SPIN_RPM = 0
export const DEFAULT_SPIN_AXIS_DEG = 0

export interface Controls {
  velocity_kmph: number
  angle_deg: number
  dt: number
  adaptive: boolean
  dragCoefficient: number
  gravityModel: GravityModel
  densityModel: DensityModel
  radius: number
  autoSpeed: boolean
  speed: number
  spinRate: number
  spinAxisDeg: number
}

export function circularSpeed(radius: number): number {
  return Math.sqrt(MU / radius)
}

export const INITIAL_BALLISTIC_CONTROLS: Controls = {
  velocity_kmph: 170,
  angle_deg: 35,
  dt: 0.01,
  adaptive: false,
  dragCoefficient: DRAG_COEFFICIENT_DEFAULT,
  gravityModel: 'constant',
  densityModel: 'constant',
  radius: DEFAULT_ORBITAL_RADIUS,
  autoSpeed: true,
  speed: circularSpeed(DEFAULT_ORBITAL_RADIUS),
  spinRate: DEFAULT_SPIN_RPM,
  spinAxisDeg: DEFAULT_SPIN_AXIS_DEG,
}

export const INITIAL_ORBITAL_CONTROLS: Controls = {
  ...INITIAL_BALLISTIC_CONTROLS,
  gravityModel: 'newtonian',
  densityModel: 'none',
  dt: 1,
}

export function buildRequest(controls: Controls): SimulateRequest {
  const orbital = controls.gravityModel !== 'constant'
  const dragModel = controls.densityModel === 'none' ? 'constant' : controls.densityModel
  const coefficient = controls.densityModel === 'none' ? 0 : controls.dragCoefficient

  const request: SimulateRequest = {
    velocity_kmph: controls.velocity_kmph,
    angle_deg: controls.angle_deg,
    dt: controls.dt,
    adaptive: controls.adaptive,
    parameters: { drag_coefficient: coefficient },
    gravity_model: controls.gravityModel,
    drag_model: dragModel,
  }

  if (orbital) {
    const speed = controls.autoSpeed ? circularSpeed(controls.radius) : controls.speed
    request.initial_state = [controls.radius, 0, 0, 0, speed, 0]
  } else {
    request.spin_rate = controls.spinRate
    request.spin_axis_angle = controls.spinAxisDeg
  }
  return request
}

export function format(value: number, digits = 2): string {
  return value.toFixed(digits)
}

export function formatOptional(value: number | null, digits = 2): string {
  return value === null ? '-' : value.toFixed(digits)
}

const DECIMAL_FORMAT = new Intl.NumberFormat('en-US', {
  useGrouping: false,
  maximumFractionDigits: 20,
})

export function formatDecimal(value: number, significantDigits = 6): string {
  if (!Number.isFinite(value)) {
    return String(value)
  }
  return DECIMAL_FORMAT.format(Number(value.toPrecision(significantDigits)))
}

export function dtValidityMessage(input: HTMLInputElement): string {
  if (input.validity.rangeUnderflow) {
    return `刻み幅 dt は ${DT_MIN} 以上で指定してください。`
  }
  if (input.validity.rangeOverflow) {
    return `刻み幅 dt は ${DT_MAX} 以下で指定してください。`
  }
  if (input.validity.stepMismatch) {
    return `刻み幅 dt は ${DT_MIN} 単位で指定してください。`
  }
  if (input.validity.badInput) {
    return '刻み幅 dt には数値を指定してください。'
  }
  return '刻み幅 dt の値を確認してください。'
}

export interface Metric {
  key: string
  label: string
  value: string
}

export function resultMetrics(data: SimulateResponse): Metric[] {
  const { result, orbital } = data
  const adaptiveRun = data.input.adaptive ?? false
  const timestepRow: Metric[] =
    result.timestep_min !== null
      ? [
          {
            key: 'timestep',
            label: adaptiveRun ? '最短刻み' : '刻み幅',
            value: `${formatDecimal(result.timestep_min)} s`,
          },
        ]
      : []

  if (orbital) {
    return [
      { key: 'semi_major_axis', label: '長半径 a', value: `${formatOptional(orbital.semi_major_axis)} m` },
      { key: 'eccentricity', label: '離心率 e', value: format(orbital.eccentricity, 6) },
      { key: 'periapsis', label: '近点半径 r_p', value: `${format(orbital.periapsis)} m` },
      { key: 'apoapsis', label: '遠点半径 r_a', value: `${formatOptional(orbital.apoapsis)} m` },
      { key: 'period', label: '公転周期 T', value: `${formatOptional(orbital.period)} s` },
      { key: 'inclination', label: '軌道傾斜角 i', value: `${format(orbital.inclination_deg, 4)} deg` },
      { key: 'flight_time', label: '積分時間', value: `${format(result.flight_time)} s` },
      { key: 'steps', label: '積分ステップ数', value: String(result.steps) },
      ...timestepRow,
    ]
  }

  const reduction =
    result.ideal_range !== null && result.ideal_range > 0
      ? ((result.ideal_range - result.ground_range) / result.ideal_range) * 100
      : 0

  return [
    { key: 'ideal_range', label: '理想射程（抗力なし）', value: `${formatOptional(result.ideal_range)} m` },
    { key: 'ground_range', label: '実射程（抗力あり）', value: `${format(result.ground_range)} m` },
    { key: 'reduction', label: '到達距離の低減率', value: `${format(reduction, 1)} %` },
    { key: 'lateral_range', label: '横方向のずれ z', value: `${format(result.lateral_range)} m` },
    { key: 'flight_time', label: '飛行時間', value: `${format(result.flight_time)} s` },
    { key: 'impact_speed', label: '着弾速度', value: `${format(result.impact_speed)} m/s` },
    { key: 'steps', label: '積分ステップ数', value: String(result.steps) },
    ...timestepRow,
    { key: 'landed', label: '着弾', value: result.landed ? 'yes' : 'no' },
  ]
}
