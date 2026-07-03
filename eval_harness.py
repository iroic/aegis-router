import subprocess
import re
import time

# Robust regex for parsing simulation metrics
LEARNED_PATTERN = re.compile(
    r"learned.*?:.*?delivery=\s*([\d.]+)%?.*?sybil=\s*([\d.]+)%?",
    re.DOTALL | re.IGNORECASE
)

def run_simulation():
    cmd = [
        "python3", "-m", "aegis_router.event_demo",
        "--learn", "--learn-mode", "edge",
        "--nodes", "20", "--duration", "3",
        "--traffic-rate", "6", "--sybil-ratio", "0.1",
        "--drain", "2", "--state", "eval_state.json",
        "--seed", "42"
    ]
    
    try:
        start_time = time.time()
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        runtime = time.time() - start_time
        return result.stdout, runtime, True
    except subprocess.CalledProcessError as e:
        return f"{e.stderr}\n{e.stdout}", 0, False

if __name__ == "__main__":
    output, runtime, success = run_simulation()
    
    if not success:
        print("ERROR: Simulation failed")
        exit(1)

    # Search through entire output for pattern
    match = LEARNED_PATTERN.search(output)
    
    if match:
        delivery = float(match.group(1))
        sybil = float(match.group(2))
        score = delivery / 100
        
        print(f"score: {score:.4f}")
        print("metrics:")
        print(f"  delivery_ratio: {delivery:.1f}")
        print(f"  sybil_touch_ratio: {sybil:.1f}")
        print(f"  runtime: {runtime:.6f}")
    else:
        print("ERROR: Failed to extract metrics from simulation output")
        print("==== SIMULATION OUTPUT ====")
        print(output)
        print("==========================")
        exit(1)
