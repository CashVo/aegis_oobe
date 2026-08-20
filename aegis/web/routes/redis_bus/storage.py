# aegis/web/routes/redis_bus/storage.py
# Database persistence for Redis Bus observability data

import json
import logging
import sqlite3
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List, Dict
from pathlib import Path
from contextlib import asynccontextmanager

import aiosqlite

logger = logging.getLogger(__name__)


class ObservabilityStorage:
    """Persistent storage for Redis Bus observability data."""

    def __init__(self, db_path: str = "data/observability.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool: Optional[aiosqlite.Connection] = None
        self._init_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """Initialize database schema."""
        async with aiosqlite.connect(self.db_path) as db:
            # Streams table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS streams (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    agent_id TEXT NOT NULL,
                    is_broadcast BOOLEAN DEFAULT FALSE,
                    length INTEGER DEFAULT 0,
                    consumer_groups INTEGER DEFAULT 0,
                    pending_count INTEGER DEFAULT 0,
                    msgs_per_sec REAL DEFAULT 0.0,
                    oldest_entry_id TEXT,
                    newest_entry_id TEXT,
                    oldest_timestamp DATETIME,
                    newest_timestamp DATETIME,
                    first_entry_id TEXT,
                    last_entry_id TEXT,
                    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Stream snapshots for historical tracking
            await db.execute("""
                CREATE TABLE IF NOT EXISTS stream_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stream_name TEXT NOT NULL,
                    length INTEGER DEFAULT 0,
                    pending_count INTEGER DEFAULT 0,
                    consumer_groups INTEGER DEFAULT 0,
                    msgs_per_sec REAL DEFAULT 0.0,
                    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_stream_snapshots_stream_time ON stream_snapshots(stream_name, recorded_at)")

            # Messages table (archived messages)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id TEXT NOT NULL,
                    stream_name TEXT NOT NULL,
                    message_id TEXT UNIQUE NOT NULL,
                    correlation_id TEXT,
                    source_agent TEXT NOT NULL,
                    target_agent TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL,  -- JSON
                    metadata TEXT,  -- JSON
                    timestamp DATETIME NOT NULL,
                    ttl_seconds INTEGER,
                    size_bytes INTEGER DEFAULT 0,
                    token_estimate INTEGER DEFAULT 0,
                    token_usage TEXT,  -- JSON
                    status TEXT DEFAULT 'pending',
                    delivery_count INTEGER DEFAULT 1,
                    processing_latency_ms REAL,
                    retry_count INTEGER DEFAULT 0,
                    consumer_group TEXT,
                    consumer TEXT,
                    archived_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_messages_stream_time ON messages(stream_name, timestamp)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_messages_correlation ON messages(correlation_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(source_agent, target_agent)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(message_type)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status)")

            # Consumer groups table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS consumer_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stream_name TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    consumers INTEGER DEFAULT 0,
                    pending INTEGER DEFAULT 0,
                    lag INTEGER DEFAULT 0,
                    oldest_pending_age_ms INTEGER,
                    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stream_name, group_name)
                )
            """)

            # Consumers table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS consumers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stream_name TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    consumer_name TEXT NOT NULL,
                    pending INTEGER DEFAULT 0,
                    idle_ms INTEGER DEFAULT 0,
                    last_delivered_id TEXT,
                    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stream_name, group_name, consumer_name)
                )
            """)

            # Pipeline state snapshots
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    in_pipeline INTEGER DEFAULT 0,
                    done_last_hour INTEGER DEFAULT 0,
                    stuck INTEGER DEFAULT 0,
                    abandoned INTEGER DEFAULT 0,
                    dead_letter INTEGER DEFAULT 0,
                    agent_data TEXT,  -- JSON
                    stream_data TEXT,  -- JSON
                    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Token usage aggregates
            await db.execute("""
                CREATE TABLE IF NOT EXISTS token_aggregates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stream_name TEXT NOT NULL,
                    bucket_start DATETIME NOT NULL,
                    granularity TEXT NOT NULL,  -- minute, hour, day
                    cumulative_tokens INTEGER DEFAULT 0,
                    cumulative_requests INTEGER DEFAULT 0,
                    agent_data TEXT,  -- JSON
                    type_data TEXT,  -- JSON
                    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stream_name, bucket_start, granularity)
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_token_aggregates_stream_time ON token_aggregates(stream_name, bucket_start)")

            # Message actions audit log
            await db.execute("""
                CREATE TABLE IF NOT EXISTS message_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stream_name TEXT NOT NULL,
                    entry_id TEXT NOT NULL,
                    message_id TEXT,
                    action TEXT NOT NULL,  -- delete, reassign, move, retry, acknowledge
                    target_agent TEXT,
                    target_stream TEXT,
                    reason TEXT,
                    performed_by TEXT,  -- user/system
                    result TEXT,  -- success, failed
                    error_message TEXT,
                    performed_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_message_actions_stream_time ON message_actions(stream_name, performed_at)")

            await db.commit()

        logger.info(f"Observability storage initialized at {self.db_path}")

    async def close(self):
        """Close database connections."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    @asynccontextmanager
    async def _get_db(self):
        """Get database connection."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            yield db

    # ============================================
    # Stream Persistence
    # ============================================

    async def archive_stream_summary(self, summary: Dict[str, Any]):
        """Archive a stream summary snapshot."""
        async with self._get_db() as db:
            await db.execute("""
                INSERT OR REPLACE INTO streams 
                (name, agent_id, is_broadcast, length, consumer_groups, pending_count,
                 msgs_per_sec, oldest_entry_id, newest_entry_id, oldest_timestamp,
                 newest_timestamp, first_entry_id, last_entry_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                summary["name"],
                summary["agent_id"],
                summary["is_broadcast"],
                summary["length"],
                summary["consumer_groups"],
                summary["pending_count"],
                summary["msgs_per_sec"],
                summary.get("oldest_entry_id"),
                summary.get("newest_entry_id"),
                summary.get("oldest_timestamp"),
                summary.get("newest_timestamp"),
                summary.get("first_entry_id"),
                summary.get("last_entry_id"),
            ))
            await db.commit()

    async def record_stream_snapshot(self, summary: Dict[str, Any]):
        """Record a historical snapshot of stream metrics."""
        async with self._get_db() as db:
            await db.execute("""
                INSERT INTO stream_snapshots
                (stream_name, length, pending_count, consumer_groups, msgs_per_sec)
                VALUES (?, ?, ?, ?, ?)
            """, (
                summary["name"],
                summary["length"],
                summary["pending_count"],
                summary["consumer_groups"],
                summary["msgs_per_sec"],
            ))
            await db.commit()

    async def get_stream_history(
        self,
        stream_name: str,
        hours: int = 24,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get historical stream metrics."""
        async with self._get_db() as db:
            cursor = await db.execute("""
                SELECT * FROM stream_snapshots
                WHERE stream_name = ? AND recorded_at > datetime('now', ?)
                ORDER BY recorded_at DESC
                LIMIT ?
            """, (stream_name, f'-{hours} hours', limit))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ============================================
    # Message Persistence
    # ============================================

    async def archive_message(self, message: Dict[str, Any]):
        """Archive a message to persistent storage."""
        async with self._get_db() as db:
            await db.execute("""
                INSERT OR IGNORE INTO messages
                (entry_id, stream_name, message_id, correlation_id, source_agent, target_agent,
                 message_type, priority, tenant_id, user_id, action, payload, metadata,
                 timestamp, ttl_seconds, size_bytes, token_estimate, token_usage,
                 status, delivery_count, processing_latency_ms, retry_count,
                 consumer_group, consumer)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message["entry_id"],
                message["stream"],
                message["message_id"],
                message.get("correlation_id"),
                message["source_agent"],
                message["target_agent"],
                message["message_type"],
                message["priority"],
                message.get("tenant_id", ""),
                message.get("user_id", ""),
                message["action"],
                json.dumps(message.get("payload", {}), default=str),
                json.dumps(message.get("metadata", {}), default=str) if message.get("metadata") else None,
                message["timestamp"],
                message.get("ttl_seconds"),
                message.get("size_bytes", 0),
                message.get("token_estimate", 0),
                json.dumps(message.get("token_usage")) if message.get("token_usage") else None,
                message.get("status", "pending"),
                message.get("delivery_count", 1),
                message.get("processing_latency_ms"),
                message.get("retry_count", 0),
                message.get("consumer_group"),
                message.get("consumer"),
            ))
            await db.commit()

    async def archive_messages_batch(self, messages: List[Dict[str, Any]]):
        """Archive multiple messages in a batch."""
        async with self._get_db() as db:
            for message in messages:
                await db.execute("""
                    INSERT OR IGNORE INTO messages
                    (entry_id, stream_name, message_id, correlation_id, source_agent, target_agent,
                     message_type, priority, tenant_id, user_id, action, payload, metadata,
                     timestamp, ttl_seconds, size_bytes, token_estimate, token_usage,
                     status, delivery_count, processing_latency_ms, retry_count,
                     consumer_group, consumer)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    message["entry_id"],
                    message["stream"],
                    message["message_id"],
                    message.get("correlation_id"),
                    message["source_agent"],
                    message["target_agent"],
                    message["message_type"],
                    message["priority"],
                    message.get("tenant_id", ""),
                    message.get("user_id", ""),
                    message["action"],
                    json.dumps(message.get("payload", {}), default=str),
                    json.dumps(message.get("metadata", {}), default=str) if message.get("metadata") else None,
                    message["timestamp"],
                    message.get("ttl_seconds"),
                    message.get("size_bytes", 0),
                    message.get("token_estimate", 0),
                    json.dumps(message.get("token_usage")) if message.get("token_usage") else None,
                    message.get("status", "pending"),
                    message.get("delivery_count", 1),
                    message.get("processing_latency_ms"),
                    message.get("retry_count", 0),
                    message.get("consumer_group"),
                    message.get("consumer"),
                ))
            await db.commit()

    async def get_archived_messages(
        self,
        stream_name: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        message_type: Optional[str] = None,
        source_agent: Optional[str] = None,
        target_agent: Optional[str] = None,
        correlation_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query archived messages with filters."""
        conditions = []
        params = []

        if stream_name:
            conditions.append("stream_name = ?")
            params.append(stream_name)
        if start:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end:
            conditions.append("timestamp <= ?")
            params.append(end)
        if message_type:
            conditions.append("message_type = ?")
            params.append(message_type)
        if source_agent:
            conditions.append("source_agent = ?")
            params.append(source_agent)
        if target_agent:
            conditions.append("target_agent = ?")
            params.append(target_agent)
        if correlation_id:
            conditions.append("correlation_id = ?")
            params.append(correlation_id)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        async with self._get_db() as db:
            cursor = await db.execute(f"""
                SELECT * FROM messages
                {where_clause}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """, params + [limit, offset])
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_message_by_correlation(self, correlation_id: str) -> List[Dict[str, Any]]:
        """Get all messages in a correlation chain."""
        async with self._get_db() as db:
            cursor = await db.execute("""
                SELECT * FROM messages
                WHERE correlation_id = ? OR message_id = ?
                ORDER BY timestamp ASC
            """, (correlation_id, correlation_id))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ============================================
    # Consumer Group Persistence
    # ============================================

    async def archive_consumer_groups(self, stream_name: str, groups: List[Dict[str, Any]]):
        """Archive consumer group snapshots."""
        async with self._get_db() as db:
            for group in groups:
                await db.execute("""
                    INSERT OR REPLACE INTO consumer_groups
                    (stream_name, group_name, consumers, pending, lag, oldest_pending_age_ms)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    stream_name,
                    group["name"],
                    group["consumers"],
                    group["pending"],
                    group.get("lag", 0),
                    group.get("oldest_pending_age_ms"),
                ))

                for consumer in group.get("consumers_detail", []):
                    await db.execute("""
                        INSERT OR REPLACE INTO consumers
                        (stream_name, group_name, consumer_name, pending, idle_ms, last_delivered_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        stream_name,
                        group["name"],
                        consumer["name"],
                        consumer["pending"],
                        consumer["idle_ms"],
                        consumer.get("last_delivered_id"),
                    ))
            await db.commit()

    # ============================================
    # Pipeline State Persistence
    # ============================================

    async def record_pipeline_snapshot(self, state: Dict[str, Any]):
        """Record a pipeline state snapshot."""
        async with self._get_db() as db:
            await db.execute("""
                INSERT INTO pipeline_snapshots
                (in_pipeline, done_last_hour, stuck, abandoned, dead_letter, agent_data, stream_data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                state["in_pipeline"],
                state["done_last_hour"],
                state["stuck"],
                state["abandoned"],
                state["dead_letter"],
                json.dumps(state.get("by_agent", {}), default=str),
                json.dumps(state.get("by_stream", {}), default=str),
            ))
            await db.commit()

    async def get_pipeline_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get historical pipeline state."""
        async with self._get_db() as db:
            cursor = await db.execute("""
                SELECT * FROM pipeline_snapshots
                WHERE recorded_at > datetime('now', ?)
                ORDER BY recorded_at DESC
            """, (f'-{hours} hours',))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ============================================
    # Token Aggregates Persistence
    # ============================================

    async def record_token_aggregate(self, stream_name: str, data: Dict[str, Any]):
        """Record token usage aggregate for a time bucket."""
        async with self._get_db() as db:
            await db.execute("""
                INSERT OR REPLACE INTO token_aggregates
                (stream_name, bucket_start, granularity, cumulative_tokens, cumulative_requests, agent_data, type_data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                stream_name,
                data["timestamp"],
                data["granularity"],
                data["cumulative_tokens"],
                data["cumulative_requests"],
                json.dumps(data.get("by_agent", {}), default=str),
                json.dumps(data.get("by_type", {}), default=str),
            ))
            await db.commit()

    async def get_token_aggregates(
        self,
        stream_name: Optional[str] = None,
        granularity: str = "hour",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Get historical token aggregates."""
        conditions = ["granularity = ?"]
        params = [granularity]

        if stream_name:
            conditions.append("stream_name = ?")
            params.append(stream_name)
        if start:
            conditions.append("bucket_start >= ?")
            params.append(start.isoformat())
        if end:
            conditions.append("bucket_start <= ?")
            params.append(end.isoformat())

        where_clause = "WHERE " + " AND ".join(conditions)

        async with self._get_db() as db:
            cursor = await db.execute(f"""
                SELECT * FROM token_aggregates
                {where_clause}
                ORDER BY bucket_start DESC
                LIMIT ?
            """, params + [limit])
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ============================================
    # Message Actions Audit
    # ============================================

    async def record_message_action(
        self,
        stream_name: str,
        entry_id: str,
        message_id: Optional[str],
        action: str,
        target_agent: Optional[str] = None,
        target_stream: Optional[str] = None,
        reason: Optional[str] = None,
        performed_by: str = "user",
        result: str = "success",
        error_message: Optional[str] = None,
    ):
        """Record a message action for audit trail."""
        async with self._get_db() as db:
            await db.execute("""
                INSERT INTO message_actions
                (stream_name, entry_id, message_id, action, target_agent, target_stream, reason, performed_by, result, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                stream_name,
                entry_id,
                message_id,
                action,
                target_agent,
                target_stream,
                reason,
                performed_by,
                result,
                error_message,
            ))
            await db.commit()

    async def get_message_actions(
        self,
        stream_name: Optional[str] = None,
        message_id: Optional[str] = None,
        hours: int = 24,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get message action audit log."""
        conditions = ["performed_at > datetime('now', ?)"]
        params = [f'-{hours} hours']

        if stream_name:
            conditions.append("stream_name = ?")
            params.append(stream_name)
        if message_id:
            conditions.append("message_id = ?")
            params.append(message_id)

        where_clause = "WHERE " + " AND ".join(conditions)

        async with self._get_db() as db:
            cursor = await db.execute(f"""
                SELECT * FROM message_actions
                {where_clause}
                ORDER BY performed_at DESC
                LIMIT ?
            """, params + [limit])
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ============================================
    # Maintenance
    # ============================================

    async def cleanup_old_data(self, retention_days: int = 30):
        """Clean up old archived data."""
        async with self._get_db() as db:
            # Keep stream snapshots for retention period
            await db.execute("""
                DELETE FROM stream_snapshots
                WHERE recorded_at < datetime('now', ?)
            """, (f'-{retention_days} days',))

            # Keep messages for retention period
            await db.execute("""
                DELETE FROM messages
                WHERE archived_at < datetime('now', ?)
            """, (f'-{retention_days} days',))

            # Keep pipeline snapshots
            await db.execute("""
                DELETE FROM pipeline_snapshots
                WHERE recorded_at < datetime('now', ?)
            """, (f'-{retention_days} days',))

            # Keep token aggregates (longer retention - 90 days)
            await db.execute("""
                DELETE FROM token_aggregates
                WHERE recorded_at < datetime('now', ?)
            """, (f'-{retention_days * 3} days',))

            # Keep action logs (longer retention)
            await db.execute("""
                DELETE FROM message_actions
                WHERE performed_at < datetime('now', ?)
            """, (f'-{retention_days * 3} days',))

            await db.commit()

            # Vacuum to reclaim space
            await db.execute("VACUUM")


class ObservabilityArchiver:
    """Background task to periodically archive Redis bus data."""

    def __init__(
        self,
        storage: ObservabilityStorage,
        redis_service,  # RedisBusService
        interval_seconds: int = 60,
        batch_size: int = 100,
    ):
        self.storage = storage
        self.redis_service = redis_service
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the archiver background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Observability archiver started")

    async def stop(self):
        """Stop the archiver background task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Observability archiver stopped")

    async def _run_loop(self):
        """Main archiver loop."""
        while self._running:
            try:
                await self._archive_cycle()
            except Exception as e:
                logger.error(f"Archiver cycle error: {e}")

            await asyncio.sleep(self.interval_seconds)

    async def _archive_cycle(self):
        """Single archive cycle."""
        # Get all streams
        streams = await self.redis_service.list_streams()

        total_messages = 0
        for stream in streams:
            # Archive stream summary
            summary = await self.redis_service.get_stream_summary(stream)
            await self.storage.archive_stream_summary(summary)
            await self.storage.record_stream_snapshot(summary)

            # Archive consumer groups
            if summary.get("consumer_groups_detail"):
                await self.storage.archive_consumer_groups(stream, summary["consumer_groups_detail"])

            # Archive recent messages (last batch_size)
            messages = await self.redis_service.get_messages(stream, count=self.batch_size)
            if messages:
                await self.storage.archive_messages_batch(messages)
                total_messages += len(messages)

        # Archive pipeline state
        pipeline = await self.redis_service.get_pipeline_state()
        await self.storage.record_pipeline_snapshot(pipeline)

        logger.debug(f"Archived {len(streams)} streams, {total_messages} messages")


# Global instance
_observability_storage: Optional[ObservabilityStorage] = None
_archiver: Optional[ObservabilityArchiver] = None


async def get_observability_storage(db_path: str = "data/observability.db") -> ObservabilityStorage:
    """Get or create the global observability storage instance."""
    global _observability_storage
    if _observability_storage is None:
        _observability_storage = ObservabilityStorage(db_path)
        await _observability_storage.initialize()
    return _observability_storage


async def start_archiver(redis_service, interval_seconds: int = 60):
    """Start the global archiver."""
    global _archiver, _observability_storage
    if _observability_storage is None:
        _observability_storage = await get_observability_storage()
    _archiver = ObservabilityArchiver(_observability_storage, redis_service, interval_seconds)
    await _archiver.start()


async def stop_archiver():
    """Stop the global archiver."""
    global _archiver
    if _archiver:
        await _archiver.stop()
        _archiver = None