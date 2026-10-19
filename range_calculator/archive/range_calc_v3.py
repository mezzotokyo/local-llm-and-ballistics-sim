import math
from pathlib import Path

# --- GLOBAL PHYSICAL CONSTANTS & PROJECTILE SETUP ---
# These constants define the scenario and should ideally come from configuration files.

class ProjectileConstants:
    """Holds all fixed physical parameters for the simulation."""
    MAX_TIME = 300.0  # Maximum simulation time (seconds)
    GRAVITY = 9.81     # Acceleration due to gravity (m/s^2)
    AIR_DENSITY = 1.225 # Air density (kg/m^3)
    MASS = 0.149       # Object mass (kg) - Corresponds to 149g
    DIAMETER = 0.075   # Cross-section diameter (m) - Corresponds to 7.5cm
    DRAG_COEFFICIENT = 0.47 # Drag coefficient for a sphere

    @staticmethod
    def frontal_area():
        """Calculates the projectile's cross-sectional area."""
        return math.pi * (ProjectileConstants.DIAMETER / 2)**2

    @staticmethod
    def drag_scaling_factor():
        """Calculates the combined factor (1/2 * rho * A * Cd) / m."""
        area = ProjectileConstants.frontal_area()
        return 0.5 * ProjectileConstants.AIR_DENSITY * area * ProjectileConstants.DRAG_COEFFICIENT / ProjectileConstants.MASS

# --- CORE PHYSICS SIMULATION FUNCTIONS (RK4 INTEGRATOR) ---

def derivatives(state, constants):
    """
    Calculates the time derivatives (velocity and acceleration) for the current state.
    State is a tuple: (x, y, vx, vy)
    Returns: (dx/dt, dy/dt, dvx/dt, dvy/dt)
    """
    x, y, vx, vy = state
    k = constants['drag_scaling_factor']

    # Current velocity magnitude
    V = math.sqrt(vx**2 + vy**2)

    # Calculate accelerations (forces)
    ax = -k * vx * V
    ay = -k * vy * V - ProjectileConstants.GRAVITY

    # Return derivatives: dx/dt, dy/dt, dvx/dt, dvy/dt
    return vx, vy, ax, ay

class ProjectileSimulator:
    """Handles the physics simulation logic using Runge-Kutta 4th order integration."""

    def __init__(self, initial_velocity: float, launch_angle_rad: float, constants):
        # Initial state variables (x, y, vx, vy)
        self.initial_velocity = initial_velocity
        self.launch_angle_rad = launch_angle_rad
        self.k = constants['drag_scaling_factor']

        # Initial state vector: (x, y, vx, vy)
        self.state = [0.0, 0.0, initial_velocity * math.cos(launch_angle_rad), initial_velocity * math.sin(launch_angle_rad)]
        self.t = 0.0

    def calculate_ideal_range(self):
        """Calculates range assuming no air resistance."""
        return (self.initial_velocity**2 * math.sin(2 * self.launch_angle_rad)) / ProjectileConstants.GRAVITY

    def run_simulation(self, dt: float = 0.01) -> tuple[float, float]:
        """Runs the simulation until ground impact or time limit using RK4."""
        # Main loop for numerical integration
        while True:
            x, y, vx, vy = self.state
            self.t += dt

            # Termination condition check (must check against ground impact BEFORE advancing)
            if y < 0 and self.t > 0:
                # Ground impact occurred in this step interval. Use interpolation/rollback for accuracy.
                # For simplicity and focusing on RK4, we snap to ground level (y=0) and use the x position.
                # A more rigorous solution would rollback to find exact collision time, but RK4 reduces this need.
                self.state[1] = 0.0 # Set y=0
                break

            if self.t >= ProjectileConstants.MAX_TIME:
                # Time limit reached
                break

            # RK4 Steps (State Vector: x, y, vx, vy)
            # K1 = dt * F(t_n, S_n)
            k1_rates = derivatives(tuple(self.state), constants) # (vx, vy, ax, ay)
            k1 = [dt * rate for rate in k1_rates]

            # K2 evaluation uses (S_n + K1/2)
            state_k2 = [self.state[i] + k1[i]/2 for i in range(4)]
            k2_rates = derivatives(tuple(state_k2), constants)
            k2 = [dt * rate for rate in k2_rates]

            # K3 evaluation uses (S_n + K2/2)
            state_k3 = [self.state[i] + k2[i]/2 for i in range(4)]
            k3_rates = derivatives(tuple(state_k3), constants)
            k3 = [dt * rate for rate in k3_rates]

            # K4 evaluation uses (S_n + K3)
            state_k4 = [self.state[i] + k3[i] for i in range(4)]
            k4_rates = derivatives(tuple(state_k4), constants)
            k4 = [dt * rate for rate in k4_rates]

            # Next State calculation: S_{n+1} = S_n + (K1 + 2*K2 + 2*K3 + K4) / 6
            next_state = [self.state[i] + (k1[i] + 2*k2[i] + 2*k3[i] + k4[i])/6 for i in range(4)]
            self.state = next_state

        # Return final X and Total Time (assuming the loop breaks due to impact/MAX_TIME)
        return self.state[0], self.t

# --- EXECUTION AND I/O LAYER (The "Main Block") ---

if __name__ == '__main__':
    # Read input data from CSV file
    try:
        with open(Path(__file__).resolve().parent / 'data.csv', 'r', encoding='utf-8-sig') as f:
            line = f.readline().strip()
        parts = line.split(',')
        V0_KMPH = float(parts[0])
        ANGLE_DEG = float(parts[1])
    except (OSError, ValueError, UnicodeDecodeError):
        # Fallback to default values if data.csv is not found or unreadable
        V0_KMPH = 170.0 # Default Initial Velocity (km/h)
        ANGLE_DEG = 35.0  # Default Launch Angle (degrees)

    # Unit Conversion (Input Preparation)
    v0_mps = V0_KMPH * (1000 / 3600)
    angle_rad = math.radians(ANGLE_DEG)

    # Drag Scaling Factor calculation (using constants from the file/user input)
    constants = {
        'drag_scaling_factor': ProjectileConstants.drag_scaling_factor()
    }

    # 1. Ideal calculation (No drag)
    simulator_ideal = ProjectileSimulator(v0_mps, angle_rad, constants)
    range_ideal = simulator_ideal.calculate_ideal_range()

    # 2. Realistic calculation (With drag)
    simulator_rk4 = ProjectileSimulator(v0_mps, angle_rad, constants)
    range_rk4, final_time = simulator_rk4.run_simulation()

    # --- Output Results ---
    print("--- Simulation Results (RK4 Refactored) ---")
    print(f"Input Velocity: {V0_KMPH} km/h")
    print(f"Launch Angle: {ANGLE_DEG}°")
    print("\n--- Range Comparison ---")
    print(f"Ideal Range (No Drag): {range_ideal:.2f} m")
    print(f"Realistic Range (RK4, With Drag): {range_rk4:.2f} m")
    print(f"Actual Flight Time: {final_time:.2f} s")