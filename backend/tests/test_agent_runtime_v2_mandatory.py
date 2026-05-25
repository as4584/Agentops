"""
Test: Agent Runtime v2 Mandatory Enforcement (Sprint 5)

Verifies that:
1. AGENT_RUNTIME_V2 is hardcoded to True (non-configurable)
2. Legacy execution paths (_process_message_legacy, _handle_tool_calls) raise RuntimeError
3. Timeout fallback to legacy has been removed
4. All agents use bounded ReAct loop exclusively

This is a GATE test: must pass before proceeding to Phase B/C.
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.config import AGENT_RUNTIME_V2, AGENT_MAX_STEPS
from backend.agents import BaseAgent


class TestAgentRuntimeV2Mandatory:
    """Test suite for v2-only enforcement."""
    
    def test_agent_runtime_v2_is_true(self):
        """Config: AGENT_RUNTIME_V2 must be hardcoded True."""
        assert AGENT_RUNTIME_V2 is True, \
            "AGENT_RUNTIME_V2 must be hardcoded to True (not environment-configurable)"
    
    def test_agent_max_steps_configured(self):
        """Config: AGENT_MAX_STEPS must be positive and reasonable."""
        assert AGENT_MAX_STEPS > 0, "AGENT_MAX_STEPS must be positive"
        assert AGENT_MAX_STEPS <= 16, "AGENT_MAX_STEPS should be ≤ 16 (runaway prevention)"
        assert AGENT_MAX_STEPS >= 4, "AGENT_MAX_STEPS should be ≥ 4 (minimum useful)"
    
    @pytest.mark.asyncio
    async def test_legacy_path_raises_runtime_error(self):
        """Behavior: _process_message_legacy() raises RuntimeError."""
        # Initialize an agent (minimal setup)
        from backend.agents import create_agent
        from backend.llm import OllamaClient
        
        llm_client = OllamaClient()
        agent = create_agent("devops_agent", llm_client)
        
        # Attempting to call legacy path should raise
        with pytest.raises(RuntimeError) as exc_info:
            await agent._process_message_legacy("test message")
        
        assert "removed in Sprint 5" in str(exc_info.value)
        assert "v2 bounded ReAct" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_handle_tool_calls_raises_runtime_error(self):
        """Behavior: _handle_tool_calls() raises RuntimeError."""
        from backend.agents import create_agent
        from backend.llm import OllamaClient
        
        llm_client = OllamaClient()
        agent = create_agent("code_review_agent", llm_client)
        
        # Attempting to call legacy tool handler should raise
        with pytest.raises(RuntimeError) as exc_info:
            await agent._handle_tool_calls("[TOOL:echo(msg='test')]")
        
        assert "removed in Sprint 5" in str(exc_info.value)
        assert "no longer supported" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_process_message_delegates_to_v2_only(self):
        """Behavior: process_message() always calls process_message_v2()."""
        from backend.agents import create_agent
        from backend.llm import OllamaClient
        from unittest.mock import AsyncMock, patch
        
        llm_client = OllamaClient()
        agent = create_agent("security_agent", llm_client)
        
        # Mock process_message_v2 to verify it's called
        with patch.object(agent, 'process_message_v2', new_callable=AsyncMock) as mock_v2:
            mock_v2.return_value = "mocked response"
            
            result = await agent.process_message("test message")
            
            # Verify v2 was called with correct args
            mock_v2.assert_called_once_with("test message", None)
            assert result == "mocked response"
    
    def test_no_legacy_tool_warning_constant(self):
        """Code: Legacy tool warning tracker not initialized (or not used)."""
        # The _legacy_tool_warned set should either not exist or be empty
        # because the warning code path was removed
        if hasattr(BaseAgent, '_legacy_tool_warned'):
            # If it exists, it should never be populated (legacy code removed)
            assert len(BaseAgent._legacy_tool_warned) == 0, \
                "Legacy tool warning tracker should be empty (legacy code removed)"


class TestTimeoutFallbackRemoved:
    """Test suite for timeout fallback removal."""
    
    def test_no_timeout_fallback_to_legacy_in_code(self):
        """Code inspection: No call to _process_message_legacy() from timeout handler."""
        import inspect
        from backend.agents import BaseAgent
        
        # Get the source code of process_message_v2
        source = inspect.getsource(BaseAgent.process_message_v2)
        
        # Verify the timeout fallback code is not present
        assert "falling back to legacy" not in source, \
            "Timeout fallback to legacy should be removed"
        assert "_process_message_legacy(message" not in source, \
            "No call to legacy path should exist in timeout handler"
        
        # Verify error response instead
        assert "timed out" in source.lower(), \
            "Timeout handler should log timeout warning"


class TestV2ExecutorPath:
    """Test suite for v2 executor enforcement."""
    
    @pytest.mark.asyncio
    async def test_process_message_calls_process_message_v2(self):
        """Behavior: process_message() directly calls process_message_v2()."""
        from backend.agents import create_agent
        from backend.llm import OllamaClient
        from unittest.mock import AsyncMock, patch
        
        llm_client = OllamaClient()
        agent = create_agent("it_agent", llm_client)
        
        # Mock _executor_turn to prevent actual execution
        with patch.object(agent, '_executor_turn', new_callable=AsyncMock) as mock_exec:
            from backend.models import AgentTurn
            
            # Return a final turn to stop the loop
            mock_exec.return_value = AgentTurn(
                turn_id="test-turn-1",
                role="executor",
                model_id="llama3.2:3b-instruct-q8_0",
                content="Test response",
                observations=[],
                tool_calls=[],
                is_final=True
            )
            
            # Call process_message (which should use v2)
            response = await agent.process_message("test")
            
            # Verify executor was called (v2 path)
            assert mock_exec.called, "Executor should be called in v2 path"
            assert response == "Test response"


class TestConfigValidation:
    """Test suite for config consistency."""
    
    def test_config_file_hardcodes_v2_true(self):
        """Config: backend/config.py must hardcode AGENT_RUNTIME_V2=True."""
        config_path = project_root / "backend" / "config.py"
        config_source = config_path.read_text()
        
        # Should NOT use os.getenv for AGENT_RUNTIME_V2
        assert "os.getenv(\"AGENT_RUNTIME_V2\"" not in config_source, \
            "AGENT_RUNTIME_V2 should not use os.getenv (must be hardcoded)"
        
        # Should be explicitly True
        assert "AGENT_RUNTIME_V2: bool = True" in config_source, \
            "AGENT_RUNTIME_V2 must be explicitly hardcoded to True"
    
    def test_agent_init_code_no_conditional_v2_check(self):
        """Code: No runtime check for AGENT_RUNTIME_V2 in dispatcher."""
        agent_path = project_root / "backend" / "agents" / "__init__.py"
        agent_source = agent_path.read_text()
        
        # The old conditional should be gone
        assert "if AGENT_RUNTIME_V2:" not in agent_source, \
            "process_message should not conditionally dispatch based on AGENT_RUNTIME_V2"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
