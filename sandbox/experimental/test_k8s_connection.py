# test_k8s_connection.py
import subprocess


def run_kubectl(cmd: list[str]):
    """Call kubectl and return output"""
    result = subprocess.run(["kubectl"] + cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout
    else:
        return f"Error: {result.stderr}"


# Test 1: Can we see namespaces?
print("=== Test 1: List namespaces ===")
print(run_kubectl(["get", "namespaces"]))

# Test 2: Can we see pods in agent-ops namespace?
print("\n=== Test 2: List pods in agent-ops ===")
print(run_kubectl(["get", "pods", "-n", "agent-ops"]))

# Test 3: Can we create a simple job?
print("\n=== Test 3: Create test job ===")
print(
    run_kubectl(
        ["create", "job", "agentop-test", "--image=busybox", "-n", "agent-ops", "--", "echo", "Hello from Agentop"]
    )
)

print("\nIf you see output above (not errors), Agentop can control Kubernetes! ✓")
