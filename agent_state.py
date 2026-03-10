import logging
import threading
from enum import Enum

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Enumeration for agent operational states."""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"


class AgentStateManager:
    """
    Manages the agent's operational state in a thread-safe manner.
    """
    def __init__(self):
        self._state = AgentState.IDLE
        self._lock = threading.Lock()
        logger.info("AgentStateManager initialized. Initial state: %s", self._state.name)

    def get_state(self) -> AgentState:
        """Returns the current state of the agent."""
        with self._lock:
            return self._state

    def set_state(self, new_state: AgentState):
        """
        Sets the agent's state.
        Raises ValueError if new_state is not a valid AgentState.
        """
        if not isinstance(new_state, AgentState):
            logger.error("Attempted to set invalid state type: %s", type(new_state))
            raise ValueError("Invalid state provided. Must be an instance of AgentState.")

        with self._lock:
            if self._state != new_state:
                logger.info("Agent state changing from %s to %s", self._state.name, new_state.name)
                self._state = new_state
            else:
                logger.debug("Agent state is already %s. No change.", new_state.name)


# Create a single instance to be used throughout the application
agent_state_manager = AgentStateManager()