from __future__ import annotations
from enum import Enum
from core.errors.categories import ErrorCategory, DeadLetterReason

class AckStatus(Enum):
    """P0 Persistence ACK States: Eliminates Lying ACKs upon Database Failures."""
    COMMITTED           = "COMMITTED"
    EMERGENCY_JOURNALED = "EMERGENCY_JOURNALED"
    FAILED              = "FAILED"
    TIMEOUT             = "TIMEOUT"

class ScanCheckResult(Enum):
    FOUND          = "FOUND"
    NOT_FOUND      = "NOT_FOUND"
    DB_UNAVAILABLE = "DB_UNAVAILABLE"

class JobStatus(Enum):
    CREATED         = "CREATED"
    QUEUED          = "QUEUED"
    IN_FLIGHT       = "IN_FLIGHT"
    RESULT_READY    = "RESULT_READY"
    PERSIST_PENDING = "PERSIST_PENDING"
    PERSISTED       = "PERSISTED"
    COMPLETED       = "COMPLETED"
    RETRYABLE       = "RETRYABLE"
    POISON_JOB      = "POISON_JOB"
    PERMANENT_FAIL  = "PERMANENT_FAIL"
    CANCELLED       = "CANCELLED"
    DEAD_LETTER     = "DEAD_LETTER"

class JobSource(Enum):
    PATTERN      = "PATTERN"
    IMPORT       = "IMPORT"
    RETRY        = "RETRY"
    MANUAL       = "MANUAL"
    RECOVERY     = "RECOVERY"

class FragmentStatus(Enum):
    AVAILABLE   = "AVAILABLE"
    AUCTION     = "AUCTION"
    TAKEN       = "TAKEN"
    RESERVED    = "RESERVED"
    SOLD        = "SOLD"
    UNAVAILABLE = "UNAVAILABLE"
    FREE        = "FREE"
    UNKNOWN     = "UNKNOWN"
    ERROR       = "ERROR"

class EngineState(Enum):
    STOPPED          = "STOPPED"
    STARTING         = "STARTING"
    RUNNING          = "RUNNING"
    PAUSING          = "PAUSING"
    PAUSED           = "PAUSED"
    DEGRADED         = "DEGRADED"
    RECOVERING       = "RECOVERING"
    DRAINING         = "DRAINING"
    STOPPING         = "STOPPING"
    STARTUP_BLOCKED  = "STARTUP_BLOCKED"
    FAILED           = "FAILED"

class SystemHealthState(Enum):
    HEALTHY    = "HEALTHY"
    DEGRADED   = "DEGRADED"
    STALLED    = "STALLED"
    RECOVERING = "RECOVERING"
    FAILED     = "FAILED"

class DatabaseHealthState(Enum):
    HEALTHY     = "HEALTHY"
    DEGRADED    = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"

class DiskHealthState(Enum):
    HEALTHY  = "HEALTHY"
    WARNING  = "WARNING"
    CRITICAL = "CRITICAL"
    HALTED   = "HALTED"

class MemoryBudgetState(Enum):
    NORMAL          = "NORMAL"
    WARNING         = "WARNING"
    THROTTLE        = "THROTTLE"
    PAUSE_PRODUCERS = "PAUSE_PRODUCERS"
    EMERGENCY       = "EMERGENCY"

class CircuitState(Enum):
    CLOSED    = "CLOSED"
    OPEN      = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class RecycleReason(Enum):
    RECYCLE_AGE             = "RECYCLE_AGE"
    RECYCLE_ERRORS          = "RECYCLE_ERRORS"
    RECYCLE_BYTES           = "RECYCLE_BYTES"
    RECYCLE_MANUAL          = "RECYCLE_MANUAL"
    RECYCLE_CORRUPTED       = "RECYCLE_CORRUPTED"

class VerificationMode(Enum):
    OFF    = "OFF"
    SMART  = "SMART"
    ALWAYS = "ALWAYS"