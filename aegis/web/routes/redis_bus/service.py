# aegis/web/routes/redis_bus/service.py
# Business logic for Redis Bus observability

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List, Dict, Tuple
from collections import defaultdict
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from aegis.schemas.message import AegisMessage, MessageType, Priority
from aegis.bus.constants import STREAM_PREFIX, BROADCAST_STREAM, CONSUMER_GROUP_PREFIX, agent_stream
from aegis.web.core.dependencies import get_redis_client

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    tiktoken = None
    TIKTOKEN_AVAILABLE = False

logger = logging.getLogger(__name__)


class RedisBusService:
    """Service for inspecting and analyzing Redis message bus."""

    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self._encoding = None
        if TIKTOKEN_AVAILABLE and tiktoken is not None:
            try:
                self._encoding = tiktoken.get_encoding("cl100k_base")
            except Exception:
                self._encoding = None

    # ============================================
    # Stream Discovery & Summary
    # ============================================

    async def list_streams(self, pattern: str = "aegis:stream:*") -> List[str]:
        """List all streams matching pattern."""
        try:
            streams = []
            async for key in self.redis.scan_iter(match=pattern, count=100):
                stream_name = key.decode() if isinstance(key, bytes) else key
                streams.append(stream_name)
            return sorted(streams)
        except RedisError as e:
            logger.error(f"Failed to list streams: {e}")
            return []

    async def get_stream_summary(self, stream_name: str) -> Dict[str, Any]:
        """Get summary statistics for a stream."""
        try:
            pipe = self.redis.pipeline()

            # Basic stream info
            pipe.xlen(stream_name)
            pipe.xrange(stream_name, count=1)  # oldest
            pipe.xrevrange(stream_name, count=1)  # newest

            # Consumer groups
            pipe.xinfo_groups(stream_name)

            results = await pipe.execute()

            length = results[0]
            oldest_entries = results[1]
            newest_entries = results[2]
            groups = results[3]

            # Parse consumer groups
            consumer_groups = []
            total_pending = 0
            for group in groups:
                group_name = group["name"].decode() if isinstance(group["name"], bytes) else group["name"]
                pending = group["pending"]
                total_pending += pending

                # Get consumers for this group
                consumers = await self.redis.xinfo_consumers(stream_name, group_name)
                consumer_details = []
                for consumer in consumers:
                    consumer_name = consumer["name"].decode() if isinstance(consumer["name"], bytes) else consumer["name"]
                    consumer_details.append({
                        "name": consumer_name,
                        "pending": consumer["pending"],
                        "idle_ms": consumer["idle"],
                        "last_delivered_id": consumer.get("last-delivered-id"),
                    })

                consumer_groups.append({
                    "name": group_name,
                    "stream": stream_name,
                    "consumers": len(consumers),
                    "pending": pending,
                    "lag": pending,  # Simplified
                    "oldest_pending_age_ms": None,  # Would need XPENDING with detail
                    "consumers_detail": consumer_details,
                })

            # Extract timestamps from entries
            oldest_ts = None
            newest_ts = None
            oldest_id = None
            newest_id = None

            if oldest_entries:
                oldest_id = oldest_entries[0][0].decode() if isinstance(oldest_entries[0][0], bytes) else oldest_entries[0][0]
                oldest_ts = self._entry_id_to_timestamp(oldest_id)

            if newest_entries:
                newest_id = newest_entries[0][0].decode() if isinstance(newest_entries[0][0], bytes) else newest_entries[0][0]
                newest_ts = self._entry_id_to_timestamp(newest_id)

            # Calculate msgs/sec (approximate from last 5 min)
            msgs_per_sec = await self._calculate_rate(stream_name, window_seconds=300)

            return {
                "name": stream_name,
                "agent_id": stream_name.replace(STREAM_PREFIX, "").replace(":broadcast", ""),
                "is_broadcast": stream_name == BROADCAST_STREAM,
                "length": length,
                "consumer_groups": len(consumer_groups),
                "pending_count": total_pending,
                "oldest_entry_id": oldest_id,
                "newest_entry_id": newest_id,
                "oldest_timestamp": oldest_ts,
                "newest_timestamp": newest_ts,
                "msgs_per_sec": msgs_per_sec,
                "first_entry_id": oldest_id,
                "last_entry_id": newest_id,
                "consumer_groups_detail": consumer_groups,
            }

        except RedisError as e:
            logger.error(f"Failed to get stream summary for {stream_name}: {e}")
            return {
                "name": stream_name,
                "agent_id": stream_name.replace(STREAM_PREFIX, ""),
                "is_broadcast": stream_name == BROADCAST_STREAM,
                "length": 0,
                "consumer_groups": 0,
                "pending_count": 0,
                "error": str(e),
            }

    async def get_all_stream_summaries(self) -> List[Dict[str, Any]]:
        """Get summaries for all aegis streams."""
        streams = await self.list_streams()
        summaries = []
        for stream in streams:
            summary = await self.get_stream_summary(stream)
            summaries.append(summary)
        return summaries

    async def get_overview_stats(self) -> Dict[str, Any]:
        """Get global overview statistics."""
        streams = await self.list_streams()

        total_messages = 0
        total_pending = 0
        total_groups = 0
        total_rate = 0.0
        active_agents = set()

        for stream in streams:
            summary = await self.get_stream_summary(stream)
            total_messages += summary["length"]
            total_pending += summary["pending_count"]
            total_groups += summary["consumer_groups"]
            total_rate += summary["msgs_per_sec"]
            active_agents.add(summary["agent_id"])

        return {
            "total_streams": len(streams),
            "total_messages": total_messages,
            "total_pending": total_pending,
            "total_consumer_groups": total_groups,
            "active_agents": len(active_agents),
            "msgs_per_sec": total_rate,
            "avg_latency_ms": 0.0,
            "error_rate": 0.0,
            "total_tokens_24h": 0,
            "total_requests_24h": 0,
        }

    async def _calculate_rate(self, stream_name: str, window_seconds: int = 300) -> float:
        """Calculate messages per second in the last window."""
        try:
            # Use XRANGE with timestamp range
            end_id = "+"
            start_time = int((time.time() - window_seconds) * 1000)
            start_id = f"{start_time}-0"

            entries = await self.redis.xrange(stream_name, min=start_id, max=end_id, count=10000)
            return len(entries) / window_seconds
        except RedisError:
            return 0.0

    def _entry_id_to_timestamp(self, entry_id: str) -> Optional[datetime]:
        """Convert Redis stream entry ID to datetime."""
        try:
            # Entry ID format: timestamp-sequence
            timestamp_ms = int(entry_id.split("-")[0])
            return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        except (ValueError, IndexError):
            return None

    # ============================================
    # Message Operations
    # ============================================

    async def get_messages(
        self,
        stream_name: str,
        count: int = 50,
        start_id: str = "-",
        end_id: str = "+",
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Get messages from a stream with optional filtering."""
        try:
            # Get raw entries
            entries = await self.redis.xrange(stream_name, min=start_id, max=end_id, count=count * 3)  # Get extra for filtering

            messages = []
            for entry_id, fields in entries:
                entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                data = fields.get(b"data") or fields.get("data")

                if not data:
                    continue

                data_str = data.decode() if isinstance(data, bytes) else data

                try:
                    msg_data = json.loads(data_str)
                    message = AegisMessage.model_validate(msg_data)

                    # Apply filters
                    if filters and not self._matches_filters(message, filters):
                        continue

                    # Compute derived fields
                    msg_dict = self._message_to_dict(message, entry_id_str, stream_name)
                    messages.append(msg_dict)

                    if len(messages) >= count:
                        break

                except (json.JSONDecodeError, Exception) as e:
                    logger.debug(f"Failed to parse message {entry_id_str}: {e}")
                    # Include raw message
                    messages.append({
                        "entry_id": entry_id_str,
                        "stream": stream_name,
                        "message_id": "unknown",
                        "source_agent": "unknown",
                        "target_agent": "unknown",
                        "message_type": "unknown",
                        "priority": "normal",
                        "action": "unknown",
                        "timestamp": self._entry_id_to_timestamp(entry_id_str) or datetime.now(timezone.utc),
                        "status": "parse_error",
                        "raw_data": data_str[:500],
                        "parse_error": str(e),
                    })

                    if len(messages) >= count:
                        break

            return messages

        except RedisError as e:
            logger.error(f"Failed to get messages from {stream_name}: {e}")
            return []

    def _matches_filters(self, message: AegisMessage, filters: Dict[str, Any]) -> bool:
        """Check if message matches filters."""
        if filters.get("message_type") and message.message_type != filters["message_type"]:
            return False
        if filters.get("priority") and message.priority != filters["priority"]:
            return False
        if filters.get("source_agent") and message.source_agent != filters["source_agent"]:
            return False
        if filters.get("target_agent") and message.target_agent != filters["target_agent"]:
            return False
        if filters.get("correlation_id") and message.correlation_id != filters["correlation_id"]:
            return False
        if filters.get("action") and message.action != filters["action"]:
            return False
        if filters.get("start") and message.timestamp < filters["start"]:
            return False
        if filters.get("end") and message.timestamp > filters["end"]:
            return False
        if filters.get("search"):
            search = filters["search"].lower()
            if search not in message.action.lower() and search not in json.dumps(message.payload).lower():
                return False
        return True

    def _message_to_dict(self, message: AegisMessage, entry_id: str, stream: str) -> Dict[str, Any]:
        """Convert AegisMessage to dict with computed fields."""
        now = datetime.now(timezone.utc)
        msg_time = message.timestamp
        if msg_time.tzinfo is None:
            msg_time = msg_time.replace(tzinfo=timezone.utc)

        age_seconds = (now - msg_time).total_seconds()
        size_bytes = len(json.dumps(message.model_dump(), default=str).encode())

        # Token estimation
        token_estimate = self.estimate_tokens(message)
        token_usage = self.extract_token_usage(message)

        return {
            "entry_id": entry_id,
            "stream": stream,
            "message_id": message.message_id,
            "correlation_id": message.correlation_id,
            "source_agent": message.source_agent,
            "target_agent": message.target_agent,
            "message_type": message.message_type.value if isinstance(message.message_type, MessageType) else message.message_type,
            "priority": message.priority.value if isinstance(message.priority, Priority) else message.priority,
            "action": message.action,
            "timestamp": message.timestamp,
            "ttl_seconds": message.ttl_seconds,
            "size_bytes": size_bytes,
            "age_seconds": age_seconds,
            "token_estimate": token_estimate,
            "token_usage": token_usage.model_dump() if token_usage else None,
            "has_token_usage": token_usage is not None,
            "status": "pending",  # Will be updated with consumer group info
            "delivery_count": 1,
        }

    async def get_message_detail(self, stream_name: str, entry_id: str) -> Optional[Dict[str, Any]]:
        """Get full detail for a single message."""
        try:
            entries = await self.redis.xrange(stream_name, min=entry_id, max=entry_id, count=1)
            if not entries:
                return None

            entry_id_raw, fields = entries[0]
            entry_id_str = entry_id_raw.decode() if isinstance(entry_id_raw, bytes) else entry_id_raw
            data = fields.get(b"data") or fields.get("data")

            if not data:
                return None

            data_str = data.decode() if isinstance(data, bytes) else data
            msg_data = json.loads(data_str)
            message = AegisMessage.model_validate(msg_data)

            # Get consumer group status (pending/acked)
            status = "pending"
            delivery_count = 1
            consumer_group = None
            consumer = None

            # Check consumer groups for this message
            groups = await self.redis.xinfo_groups(stream_name)
            for group in groups:
                group_name = group["name"].decode() if isinstance(group["name"], bytes) else group["name"]
                pending = await self.redis.xpending_range(
                    stream_name, group_name, min=entry_id_str, max=entry_id_str, count=1
                )
                if pending:
                    status = "pending"
                    delivery_count = pending[0]["times_delivered"]
                    consumer_group = group_name
                    consumer = pending[0]["consumer"].decode() if isinstance(pending[0]["consumer"], bytes) else pending[0]["consumer"]
                    break
            else:
                # Not pending - might be acknowledged
                status = "acknowledged"

            # Compute processing latency if acknowledged
            processing_latency_ms = None
            if status == "acknowledged":
                # We don't have ack timestamp in Redis, so estimate from entry ID
                pass

            now = datetime.now(timezone.utc)
            msg_time = message.timestamp
            if msg_time.tzinfo is None:
                msg_time = msg_time.replace(tzinfo=timezone.utc)

            token_usage = self.extract_token_usage(message)
            token_usage_dict = token_usage.model_dump() if token_usage else None

            return {
                "entry_id": entry_id_str,
                "stream": stream_name,
                "message_id": message.message_id,
                "correlation_id": message.correlation_id,
                "source_agent": message.source_agent,
                "target_agent": message.target_agent,
                "message_type": message.message_type.value if isinstance(message.message_type, MessageType) else message.message_type,
                "priority": message.priority.value if isinstance(message.priority, Priority) else message.priority,
                "tenant_id": message.tenant_id,
                "user_id": message.user_id,
                "action": message.action,
                "payload": message.payload,
                "metadata": message.metadata,
                "timestamp": message.timestamp,
                "ttl_seconds": message.ttl_seconds,
                "size_bytes": len(data_str.encode()),
                "age_seconds": (now - msg_time).total_seconds(),
                "token_estimate": self.estimate_tokens(message),
                "token_usage": token_usage_dict,
                "status": status,
                "delivery_count": delivery_count,
                "processing_latency_ms": processing_latency_ms,
                "retry_count": delivery_count - 1,
                "consumer_group": consumer_group,
                "consumer": consumer,
            }

        except (RedisError, json.JSONDecodeError, Exception) as e:
            logger.error(f"Failed to get message detail: {e}")
            return None

    async def get_pending_messages(self, stream_name: str, group_name: str, count: int = 100) -> List[Dict[str, Any]]:
        """Get pending messages for a consumer group."""
        try:
            pending = await self.redis.xpending_range(stream_name, group_name, min="-", max="+", count=count)
            results = []

            for p in pending:
                entry_id = p["message_id"].decode() if isinstance(p["message_id"], bytes) else p["message_id"]
                consumer = p["consumer"].decode() if isinstance(p["consumer"], bytes) else p["consumer"]

                # Get message data
                entries = await self.redis.xrange(stream_name, min=entry_id, max=entry_id, count=1)
                if entries:
                    _, fields = entries[0]
                    data = fields.get(b"data") or fields.get("data")
                    if data:
                        data_str = data.decode() if isinstance(data, bytes) else data
                        try:
                            msg_data = json.loads(data_str)
                            message = AegisMessage.model_validate(msg_data)
                            msg_dict = self._message_to_dict(message, entry_id, stream_name)
                            msg_dict["status"] = "pending"
                            msg_dict["delivery_count"] = p["times_delivered"]
                            msg_dict["consumer_group"] = group_name
                            msg_dict["consumer"] = consumer
                            msg_dict["idle_ms"] = p["time_since_delivered"]
                            results.append(msg_dict)
                        except Exception:
                            pass

            return results
        except RedisError as e:
            logger.error(f"Failed to get pending messages: {e}")
            return []

    # ============================================
    # Token Estimation
    # ============================================

    def estimate_tokens(self, message: AegisMessage) -> int:
        """Estimate token count for a message."""
        # Try to extract from payload/metadata first
        token_usage = self.extract_token_usage(message)
        if token_usage:
            return token_usage.total_tokens

        # Estimate from text content
        text_parts = [
            message.action,
            json.dumps(message.payload, default=str),
            json.dumps(message.metadata, default=str),
        ]
        full_text = " ".join(text_parts)

        if self._encoding:
            try:
                return len(self._encoding.encode(full_text))
            except Exception:
                pass

        # Fallback: ~4 chars per token
        return max(1, len(full_text) // 4)

    def extract_token_usage(self, message: AegisMessage) -> Optional["TokenUsage"]:
        """Extract token usage from message payload/metadata."""
        # Check payload
        if "token_usage" in message.payload:
            tu = message.payload["token_usage"]
            if isinstance(tu, dict):
                return TokenUsage(
                    prompt_tokens=tu.get("prompt_tokens", 0),
                    completion_tokens=tu.get("completion_tokens", 0),
                    total_tokens=tu.get("total_tokens", 0),
                    estimated_cost_usd=tu.get("estimated_cost_usd"),
                    model=tu.get("model"),
                )

        # Check metadata
        if "token_usage" in message.metadata:
            tu = message.metadata["token_usage"]
            if isinstance(tu, dict):
                return TokenUsage(
                    prompt_tokens=tu.get("prompt_tokens", 0),
                    completion_tokens=tu.get("completion_tokens", 0),
                    total_tokens=tu.get("total_tokens", 0),
                    estimated_cost_usd=tu.get("estimated_cost_usd"),
                    model=tu.get("model"),
                )

        # Check for tokens field
        if "tokens" in message.payload:
            tokens = message.payload["tokens"]
            if isinstance(tokens, int):
                return TokenUsage(total_tokens=tokens, estimated=True)
            elif isinstance(tokens, dict):
                return TokenUsage(
                    prompt_tokens=tokens.get("prompt", 0),
                    completion_tokens=tokens.get("completion", 0),
                    total_tokens=tokens.get("total", tokens.get("prompt", 0) + tokens.get("completion", 0)),
                )

        return None

    # ============================================
    # Pipeline State
    # ============================================

    async def get_pipeline_state(self, stuck_threshold_minutes: int = 5) -> Dict[str, Any]:
        """Get overall pipeline health state."""
        streams = await self.list_streams()

        total_in_pipeline = 0
        total_done = 0
        total_stuck = 0
        total_abandoned = 0
        total_dead_letter = 0

        by_agent = defaultdict(lambda: {
            "agent_id": "",
            "in_pipeline": 0,
            "done_last_hour": 0,
            "stuck": 0,
            "abandoned": 0,
            "latencies": [],
            "errors": 0,
            "total": 0,
        })

        by_stream = {}
        stuck_threshold_ms = stuck_threshold_minutes * 60 * 1000
        now_ms = time.time() * 1000
        hour_ago_ms = now_ms - 3600000

        for stream in streams:
            summary = await self.get_stream_summary(stream)
            agent_id = summary["agent_id"]
            by_agent[agent_id]["agent_id"] = agent_id

            # In pipeline = pending messages
            pending = summary["pending_count"]
            total_in_pipeline += pending
            by_agent[agent_id]["in_pipeline"] += pending

            # Done last hour - approximate from rate
            msgs_per_sec = summary["msgs_per_sec"]
            estimated_done = int(msgs_per_sec * 3600)
            total_done += estimated_done
            by_agent[agent_id]["done_last_hour"] += estimated_done

            # Stuck messages (pending > threshold with retries)
            # This would need consumer group inspection
            # For now, estimate from pending and rate
            if pending > 0 and msgs_per_sec == 0:
                total_stuck += pending
                by_agent[agent_id]["stuck"] += pending

            # Abandoned (expired TTL)
            # Would need to check message TTLs
            # Placeholder
            by_stream[stream] = {
                "stream": stream,
                "agent_id": agent_id,
                "in_pipeline": pending,
                "done_last_hour": estimated_done,
                "stuck": pending if pending > 0 and msgs_per_sec == 0 else 0,
                "abandoned": 0,
                "oldest_pending_age_sec": 0,
            }

        # Compute averages
        for agent_data in by_agent.values():
            if agent_data["latencies"]:
                agent_data["avg_latency_ms"] = sum(agent_data["latencies"]) / len(agent_data["latencies"])
            if agent_data["total"] > 0:
                agent_data["error_rate"] = agent_data["errors"] / agent_data["total"]

        return {
            "in_pipeline": total_in_pipeline,
            "done_last_hour": total_done,
            "stuck": total_stuck,
            "abandoned": total_abandoned,
            "dead_letter": total_dead_letter,
            "by_agent": dict(by_agent),
            "by_stream": by_stream,
        }

    # ============================================
    # Chart Data
    # ============================================

    async def get_token_chart_data(
        self,
        stream_name: str,
        limit: int = 100,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get token usage data for a stream's messages."""
        # Build time range
        start_id = "-"
        end_id = "+"

        if start:
            start_ms = int(start.timestamp() * 1000)
            start_id = f"{start_ms}-0"
        if end:
            end_ms = int(end.timestamp() * 1000)
            end_id = f"{end_ms}-0"

        messages = await self.get_messages(stream_name, count=limit * 2, start_id=start_id, end_id=end_id)

        data_points = []
        total_tokens = 0

        for msg in messages[:limit]:
            tokens = msg.get("token_estimate", 0)
            token_usage = msg.get("token_usage")

            prompt_tokens = 0
            completion_tokens = 0
            estimated = True

            if token_usage:
                prompt_tokens = token_usage.get("prompt_tokens", 0)
                completion_tokens = token_usage.get("completion_tokens", 0)
                if prompt_tokens or completion_tokens:
                    estimated = False
                    tokens = token_usage.get("total_tokens", tokens)

            total_tokens += tokens

            data_points.append({
                "entry_id": msg["entry_id"],
                "message_id": msg["message_id"],
                "timestamp": msg["timestamp"],
                "source_agent": msg["source_agent"],
                "target_agent": msg["target_agent"],
                "action": msg["action"],
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": tokens,
                "estimated": estimated,
            })

        return {
            "stream": stream_name,
            "data_points": data_points,
            "total_messages": len(data_points),
            "total_tokens": total_tokens,
            "avg_tokens_per_message": total_tokens / len(data_points) if data_points else 0,
        }

    async def get_cumulative_chart_data(
        self,
        start: datetime,
        end: datetime,
        granularity: str = "hour",
        agent_filter: Optional[List[str]] = None,
        type_filter: Optional[List[str]] = None,
        stream_filter: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Get cumulative token/request data with date range filtering."""
        streams = await self.list_streams()

        if stream_filter:
            streams = [s for s in streams if s in stream_filter]

        # Determine time bucket size
        bucket_seconds = {"minute": 60, "hour": 3600, "day": 86400}.get(granularity, 3600)

        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        num_buckets = max(1, (end_ms - start_ms) // (bucket_seconds * 1000) + 1)

        # Initialize buckets
        buckets = {}
        for i in range(num_buckets):
            bucket_start = start_ms + i * bucket_seconds * 1000
            bucket_dt = datetime.fromtimestamp(bucket_start / 1000, tz=timezone.utc)
            buckets[bucket_start] = {
                "timestamp": bucket_dt,
                "cumulative_tokens": 0,
                "cumulative_requests": 0,
                "by_agent": defaultdict(lambda: {"tokens": 0, "requests": 0}),
                "by_type": defaultdict(lambda: {"tokens": 0, "requests": 0}),
            }

        all_agents = set()
        all_types = set()
        total_tokens = 0
        total_requests = 0

        # Process messages from all streams
        for stream in streams:
            try:
                entries = await self.redis.xrange(stream, min=f"{start_ms}-0", max=f"{end_ms}-0", count=5000)

                for entry_id, fields in entries:
                    data = fields.get(b"data") or fields.get("data")
                    if not data:
                        continue

                    data_str = data.decode() if isinstance(data, bytes) else data
                    try:
                        msg_data = json.loads(data_str)
                        message = AegisMessage.model_validate(msg_data)

                        # Apply filters
                        if agent_filter and message.source_agent not in agent_filter and message.target_agent not in agent_filter:
                            continue
                        if type_filter and message.message_type.value not in type_filter:
                            continue

                        all_agents.add(message.source_agent)
                        all_agents.add(message.target_agent)
                        all_types.add(message.message_type.value)

                        # Token count
                        tokens = self.estimate_tokens(message)

                        # Find bucket
                        entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                        entry_timestamp = int(entry_id_str.split("-")[0])
                        bucket_start = (entry_timestamp // (bucket_seconds * 1000)) * (bucket_seconds * 1000)

                        if bucket_start in buckets:
                            bucket = buckets[bucket_start]
                            bucket["cumulative_tokens"] += tokens
                            bucket["cumulative_requests"] += 1
                            bucket["by_agent"][message.source_agent]["tokens"] += tokens
                            bucket["by_agent"][message.source_agent]["requests"] += 1
                            bucket["by_type"][message.message_type.value]["tokens"] += tokens
                            bucket["by_type"][message.message_type.value]["requests"] += 1

                            total_tokens += tokens
                            total_requests += 1

                    except Exception:
                        continue

            except RedisError:
                continue

        # Build cumulative series
        sorted_buckets = sorted(buckets.items())
        cumulative_tokens = 0
        cumulative_requests = 0
        data_points = []

        for bucket_start, bucket in sorted_buckets:
            cumulative_tokens += bucket["cumulative_tokens"]
            cumulative_requests += bucket["cumulative_requests"]

            data_points.append({
                "timestamp": bucket["timestamp"],
                "cumulative_tokens": cumulative_tokens,
                "cumulative_requests": cumulative_requests,
                "by_agent": dict(bucket["by_agent"]),
                "by_type": dict(bucket["by_type"]),
            })

        return {
            "data_points": data_points,
            "granularity": granularity,
            "date_range": {"start": start, "end": end},
            "total_tokens": total_tokens,
            "total_requests": total_requests,
            "agents": sorted(list(all_agents)),
            "message_types": sorted(list(all_types)),
        }

    # ============================================
    # Message Actions
    # ============================================

    async def delete_message(self, stream_name: str, entry_id: str) -> bool:
        """Delete a message from a stream."""
        try:
            result = await self.redis.xdel(stream_name, entry_id)
            return result > 0
        except RedisError as e:
            logger.error(f"Failed to delete message: {e}")
            return False

    async def reassign_message(
        self,
        stream_name: str,
        entry_id: str,
        new_target_agent: str,
    ) -> Optional[str]:
        """Reassign message to a different target agent (re-publish to new stream)."""
        try:
            # Get original message
            entries = await self.redis.xrange(stream_name, min=entry_id, max=entry_id, count=1)
            if not entries:
                return None

            _, fields = entries[0]
            data = fields.get(b"data") or fields.get("data")
            if not data:
                return None

            data_str = data.decode() if isinstance(data, bytes) else data
            msg_data = json.loads(data_str)
            msg_data["target_agent"] = new_target_agent
            msg_data["metadata"] = msg_data.get("metadata", {})
            msg_data["metadata"]["reassigned_from"] = stream_name
            msg_data["metadata"]["reassigned_at"] = datetime.now(timezone.utc).isoformat()
            msg_data["message_id"] = str(UUID(msg_data["message_id"]))  # Keep same ID or generate new?

            # Publish to new agent's stream
            from aegis.bus.constants import agent_stream
            new_stream = agent_stream(new_target_agent)
            new_entry_id = await self.redis.xadd(new_stream, {"data": json.dumps(msg_data, default=str)})

            return new_entry_id

        except Exception as e:
            logger.error(f"Failed to reassign message: {e}")
            return None

    async def move_message(
        self,
        source_stream: str,
        entry_id: str,
        target_stream: str,
    ) -> Optional[str]:
        """Move message to a different stream."""
        try:
            entries = await self.redis.xrange(source_stream, min=entry_id, max=entry_id, count=1)
            if not entries:
                return None

            _, fields = entries[0]
            data = fields.get(b"data") or fields.get("data")
            if not data:
                return None

            data_str = data.decode() if isinstance(data, bytes) else data

            # Add to target stream
            new_entry_id = await self.redis.xadd(target_stream, {"data": data_str})

            # Delete from source
            await self.redis.xdel(source_stream, entry_id)

            return new_entry_id

        except Exception as e:
            logger.error(f"Failed to move message: {e}")
            return None

    async def retry_message(self, stream_name: str, entry_id: str) -> Optional[str]:
        """Retry a message by re-publishing it to the same stream."""
        try:
            entries = await self.redis.xrange(stream_name, min=entry_id, max=entry_id, count=1)
            if not entries:
                return None

            _, fields = entries[0]
            data = fields.get(b"data") or fields.get("data")
            if not data:
                return None

            data_str = data.decode() if isinstance(data, bytes) else data
            msg_data = json.loads(data_str)
            msg_data["metadata"] = msg_data.get("metadata", {})
            msg_data["metadata"]["retried_at"] = datetime.now(timezone.utc).isoformat()
            msg_data["metadata"]["retry_count"] = msg_data["metadata"].get("retry_count", 0) + 1

            new_entry_id = await self.redis.xadd(stream_name, {"data": json.dumps(msg_data, default=str)})
            return new_entry_id

        except Exception as e:
            logger.error(f"Failed to retry message: {e}")
            return None

    async def acknowledge_message(self, stream_name: str, group_name: str, entry_id: str) -> bool:
        """Acknowledge a pending message."""
        try:
            result = await self.redis.xack(stream_name, group_name, entry_id)
            return result > 0
        except RedisError as e:
            logger.error(f"Failed to acknowledge message: {e}")
            return False


# ============================================
# TokenUsage model (defined here to avoid circular import)
# ============================================

class TokenUsage:
    """Token usage container."""
    def __init__(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        estimated_cost_usd: Optional[float] = None,
        model: Optional[str] = None,
        estimated: bool = False,
    ):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.estimated_cost_usd = estimated_cost_usd
        self.model = model
        self.estimated = estimated

    def model_dump(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "model": self.model,
            "estimated": self.estimated,
        }