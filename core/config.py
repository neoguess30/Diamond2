MAX_GLOBAL_QUEUE        = 50000
MAX_PATTERN_QUEUE       = 5000
MAX_WRITER_QUEUE        = 50000
MAX_RETRY_QUEUE         = 50000
MAX_FILE_BUFFER_LINES   = 5000
MAX_ACTIVE_PRODUCERS    = 4
MAX_LRU_CACHE_SIZE      = 100000
UI_BATCH_SIZE           = 50
UI_BATCH_FLUSH_SEC      = 0.100
UI_LOG_THROTTLE_SEC     = 0.250

MAX_TX_AGE_SEC          = 2.0
MAX_TX_RECORD_COUNT     = 50
MAX_COMMIT_RETRIES      = 5
COMMIT_RETRY_BACKOFF_BASE_SEC = 0.05
PRODUCER_MAX_BLOCK_SEC  = 300.0
MAX_QUEUE_WAIT_SEC      = 1800.0
MAX_JOB_RUNTIME_SEC     = 60.0
MAX_JOB_LIFECYCLE_SEC   = 2400.0
MAX_TOTAL_RETRY_BUDGET  = 6
MAX_RETRY_AGE_SEC       = 300.0
SHUTDOWN_DEADLINE_SEC   = 15.0
MAX_RESPONSE_BYTES      = 2 * 1024 * 1024

# Database Settings
DB_SYNCHRONOUS_MODE     = "NORMAL"
DB_TEMP_STORE           = "FILE"
DB_BUSY_TIMEOUT_MS      = 10000
DB_WRITER_CACHE_KIB     = -4000
DB_READER_CACHE_KIB     = -1000

# Storage & WAL Thresholds
DISK_HEALTHY_GB         = 5.0
DISK_WARNING_GB         = 2.0
DISK_CRITICAL_GB        = 1.0
DISK_HALT_WRITES_GB     = 0.50
WAL_WARNING_MB          = 50.0
WAL_CRITICAL_MB         = 200.0

# Export & Emergency Journal Rotation Bounds
MAX_EXPORT_FILE_BYTES            = 5 * 1024 * 1024    # 5 MB per exported TXT chunk file
MAX_EMERGENCY_FILE_BYTES         = 10 * 1024 * 1024   # 10 MB per emergency JSONL chunk
MAX_EMERGENCY_TOTAL_STORAGE_BYTES = 500 * 1024 * 1024  # 500 MB max emergency storage pool

# Long-Term Retention Policies
HEALTH_SNAPSHOT_RETENTION_DAYS   = 7                  # Keep max 7 days of raw 60s health telemetry
DEAD_LETTER_RETENTION_DAYS       = 30                 # Keep max 30 days of DLQ logs

# Network Constraints
CONNECT_TIMEOUT_SEC     = 5.0
READ_TIMEOUT_SEC        = 8.0
MAX_HTTP_REDIRECTS      = 3
GLOBAL_MAX_REQ_PER_SEC  = 50.0