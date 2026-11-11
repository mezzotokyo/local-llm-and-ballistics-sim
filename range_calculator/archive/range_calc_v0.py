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

    @classmethod
    def frontal_area(cls):
        """Calculates the projectile's cross-sectional area."""
        return math.pi * (cls.DIAMETER / 2)**2

    @classmethod
    def drag_scaling_factor(cls):
        """Calculates the combined factor (1/2 * rho * A * Cd) / m."""
        area = cls.frontal_area()
        return 0.5 * cls.AIR_DENSITY * area * cls.DRAG_COEFFICIENT / cls.MASS

# --- CORE PHYSICS SIMULATION FUNCTIONS (PURE LOGIC) ---
# These functions take all necessary data as arguments and produce results, independent of I/O.

def calculate_range_ideal(v0_mps: float, launch_angle_rad: float) -> float:
    """
    Calculates range assuming no air resistance (ideal projectile motion).
    v0_mps: Initial velocity in m/s.
    launch_angle_rad: Launch angle in radians.
    """
    # R = (v0^2 * sin(2*theta)) / G
    range_m = (v0_mps**2 * math.sin(2 * launch_angle_rad)) / ProjectileConstants.GRAVITY
    return range_m

def calculate_range_with_drag(initial_velocity_mps: float, launch_angle_rad: float) -> tuple[float, float]:
    """
    Simulates projectile range considering quadratic air resistance (Euler integration).

    Returns: (final_range_m, final_time_s)
    """
    dt = 0.01  # Fixed simulation timestep (crucial for consistency)

    # Initial state
    vx = initial_velocity_mps * math.cos(launch_angle_rad)
    vy = initial_velocity_mps * math.sin(launch_angle_rad)
    x = 0.0
    y = 0.0
    t = 0.0

    # Pre-calculate the drag proportionality constant (k)
    k = ProjectileConstants.drag_scaling_factor()

    while True:
        # Check termination conditions (ground impact OR time limit)
        if y < 0 and t > 0: # Ensure it started above ground
            # Linear interpolation for more accurate range upon impact (improved from original)
            dy_predicted = vy * dt
            dx_predicted = vx * dt
            # The time ratio is how much extra time was needed to drop |y| back to 0
            ratio = -y / (dy_predicted) if dy_predicted != 0 else 1.0
            
            # Apply correction: assume constant velocity during small dt step to estimate X at Y=0.
            x += vx * dt * ratio 
            y = 0 # Set to ground level
            break

        if t >= ProjectileConstants.MAX_TIME:
            # Time limit reached before ground impact - return current position
            break

        # --- Kinematics Update ---
        
        v = math.sqrt(vx**2 + vy**2)

        # Drag acceleration components (a_drag = -k * v_vector * v)
        ax = -k * vx * v
        ay = -k * vy * v - ProjectileConstants.GRAVITY # Includes gravity

        # Update velocity (Euler step)
        vx += ax * dt
        vy += ay * dt

        # Update position
        x += vx * dt
        y += vy * dt
        t += dt

    return x, t

# --- EXECUTION AND I/O LAYER (The "Main Block") ---

if __name__ == '__main__':
    # ============================================================
    # I/O Layer: Reading Input and Handling Defaults (FILE DEPENDENCY)
    # ============================================================
    file_path = Path(__file__).resolve().parent / 'data.csv'
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            line = f.readline().strip()
        if line:
            # Successfully read data from file
            v0_kph, angle_deg = map(float, line.split(','))
        else:
            # Fallback if file is empty/unreadable but opened successfully
            v0_kph, angle_deg = 150.0, 40.0
    except FileNotFoundError:
        print(f"Warning: {file_path} not found. Using default values.")
        v0_kph, angle_deg = 150.0, 40.0
    except Exception as e:
        # Catch other parsing errors (e.g., incorrect format)
        print(f"Error reading file: {e}. Using default values.")
        v0_kph, angle_deg = 150.0, 40.0
    
    # Unit Conversion (Input Preparation)
    v0_mps = v0_kph * (1000 / 3600)
    angle_rad = math.radians(angle_deg)

    # ============================================================
    # Core Calculation Layer (Pure Function Calls)
    # ============================================================

    # 1. Ideal calculation (No drag)
    range_ideal = calculate_range_ideal(v0_mps, angle_rad)

    # 2. Realistic calculation (With drag)
    range_drag, final_time = calculate_range_with_drag(v0_mps, angle_rad)

    # ============================================================
    # I/O Layer: Output Results (PRINTING TO STANDARD OUTPUT)
    # ============================================================
    print("--- Simulation Results ---")
    print(f"Input Velocity: {v0_kph} km/h")
    print(f"Launch Angle: {angle_deg}°")
    print("\n--- Range Comparison ---")
    print(f"Ideal Range (No Drag): {range_ideal:.2f} m")
    print(f"Realistic Range (With Drag): {range_drag:.2f} m")
    print(f"Actual Flight Time: {final_time:.2f} s")