export type GravityModel = 'constant' | 'newtonian' | 'j2'
export type DragModel = 'constant' | 'exponential' | 'tabulated'

export interface PhysicsParameters {
  drag_coefficient?: number
}

export interface SimulateRequest {
  velocity_kmph: number
  angle_deg: number
  dt: number
  adaptive: boolean
  parameters?: PhysicsParameters
  gravity_model?: GravityModel
  drag_model?: DragModel
  initial_state?: number[] | null
  spin_rate?: number
  spin_axis_angle?: number
}

export interface TrajectoryPoint {
  t: number
  x: number
  y: number
  z: number
  vx: number
  vy: number
  speed: number
}

export interface SimulateResult {
  ideal_range: number | null
  ground_range: number
  flight_time: number
  impact_speed: number
  landed: boolean
  timed_out: boolean
  steps: number
  timestep_min: number | null
  timestep_max: number | null
  lateral_range: number
}

export interface OrbitalElements {
  specific_energy: number
  semi_major_axis: number | null
  eccentricity: number
  periapsis: number
  apoapsis: number | null
  period: number | null
  inclination_deg: number
}

export interface SimulateResponse {
  input: SimulateRequest
  result: SimulateResult
  orbital: OrbitalElements | null
  trajectory: TrajectoryPoint[]
}
