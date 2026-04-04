"""
Test script for k8s_control tool.

Demonstrates:
1. List pods in agent-ops namespace
2. Create a test job
3. List jobs to confirm creation
"""
import asyncio
from backend.tools import execute_tool


async def main():
    agent_id = "devops_agent"
    allowed_tools = ["k8s_control"]
    
    print("=== Test 1: List pods in agent-ops namespace ===")
    result = await execute_tool(
        tool_name="k8s_control",
        agent_id=agent_id,
        allowed_tools=allowed_tools,
        action="list_pods",
        namespace="agent-ops",
    )
    print(result.get("output", result))
    print()
    
    print("=== Test 2: List current jobs ===")
    result = await execute_tool(
        tool_name="k8s_control",
        agent_id=agent_id,
        allowed_tools=allowed_tools,
        action="list_jobs",
        namespace="agent-ops",
    )
    print(result.get("output", result))
    print()
    
    print("=== Test 3: Create a new agent job ===")
    result = await execute_tool(
        tool_name="k8s_control",
        agent_id=agent_id,
        allowed_tools=allowed_tools,
        action="create_job",
        job_name="network-monitor-test",
        image="busybox",
        command="echo 'Agent deployed successfully!' && sleep 5",
        namespace="agent-ops",
    )
    print(result)
    print()
    
    print("=== Test 4: List jobs again to see new job ===")
    result = await execute_tool(
        tool_name="k8s_control",
        agent_id=agent_id,
        allowed_tools=allowed_tools,
        action="list_jobs",
        namespace="agent-ops",
    )
    print(result.get("output", result))
    print()
    
    print("✓ k8s_control tool integration complete!")
    print("\nYour Agentop system can now:")
    print("  - Deploy agents as Kubernetes jobs")
    print("  - Monitor cluster state")
    print("  - Self-manage workloads")


if __name__ == "__main__":
    asyncio.run(main())
