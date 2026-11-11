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

# --- CORE PHYSICS SIMULATION FUNCTIONS (PURE LOGIC) ---

class ProjectileSimulator:
    """Handles the physics simulation logic using Euler integration."""

    def __init__(self, initial_velocity: float, launch_angle_rad: float, constants):
        # Initial state variables (equivalent to the inputs of the old function)
        self.initial_velocity = initial_velocity
        self.launch_angle_rad = launch_angle_rad
        self.k = constants['drag_scaling_factor']

        # Simulation state variables
        self.vx = initial_velocity * math.cos(launch_angle_rad)
        self.vy = initial_velocity * math.sin(launch_angle_rad)
        self.x = 0.0
        self.y = 0.0
        self.t = 0.0

    def calculate_ideal_range(self):
        """Calculates range assuming no air resistance."""
        return (self.initial_velocity**2 * math.sin(2 * self.launch_angle_rad)) / ProjectileConstants.GRAVITY

    def run_simulation(self, dt: float = 0.01) -> tuple[float, float]:
        """Runs the simulation until ground impact or time limit."""
        while True:
            # Termination conditions check
            if self.y < 0 and self.t > 0: # Ground impact check
                # Linear interpolation for improved accuracy upon impact (original code detail)
                dy_predicted = self.vy * dt
                dx_predicted = self.vx * dt
                ratio = -self.y / (dy_predicted) if dy_predicted != 0 else 1.0
                self.x += self.vx * dt * ratio 
                self.y = 0 # Set to ground level
                break

            if self.t >= ProjectileConstants.MAX_TIME:
                # Time limit reached
                break

            # Kinematics Update (Drag and Gravity included)
            v = math.sqrt(self.vx**2 + self.vy**2)

            # Drag acceleration components
            ax = -self.k * self.vx * v
            ay = -self.k * self.vy * v - ProjectileConstants.GRAVITY

            # Update velocity (Euler step)
            self.vx += ax * dt
            self.vy += ay * dt

            # Update position
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.t += dt
        
        return self.x, self.t

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
    simulator_drag = ProjectileSimulator(v0_mps, angle_rad, constants)
    range_drag, final_time = simulator_drag.run_simulation()

    # --- Output Results ---
    print("--- Simulation Results ---")
    print(f"Input Velocity: {V0_KMPH} km/h")
    print(f"Launch Angle: {ANGLE_DEG}°")
    print("\n--- Range Comparison ---")
    print(f"Ideal Range (No Drag): {range_ideal:.2f} m")
    print(f"Realistic Range (With Drag): {range_drag:.2f} m")
    print(f"Actual Flight Time: {final_time:.2f} s")