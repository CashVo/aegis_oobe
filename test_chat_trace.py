#!/usr/bin/env python3
"""Test script to trace a chat message through the Redis bus."""

import asyncio
import json
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis
from aegis.schemas.message import AegisMessage, MessageType, Priority


async def trace_chat_message():
    """Send a chat message and trace its flow through Redis streams."""
    
    # Connect to Redis
    redis = aioredis.Redis(
        host="127.0.0.1", 
        port=6379, 
        db=0, 
        decode_responses=True
    )
    
    session_id = f"trace-test-{uuid.uuid4().hex[:8]}"
    response_channel = f"aegis:stream:cli:{session_id}"
    consumer_group = f"cli-chat-{session_id}"
    
    print(f"\n{'='*80}")
    print(f"TRACING CHAT MESSAGE")
    print(f"Session ID: {session_id}")
    print(f"Response Channel: {response_channel}")
    print(f"{'='*80}\n")
    
    # Create consumer group for response channel
    try:
        await redis.xgroup_create(response_channel, consumer_group, id="0", mkstream=True)
        print(f"✓ Created consumer group '{consumer_group}' on '{response_channel}'")
    except Exception as e:
        if "BUSYGROUP" not in str(e):
            print(f"Error creating consumer group: {e}")
    
    # Build the message
    correlation_id = str(uuid.uuid4())
    message = AegisMessage(
        correlation_id=correlation_id,
        source_agent="cli",
        target_agent="torchestrator",
        message_type=MessageType.REQUEST,
        tenant_id="default",
        user_id="root",
        action="torchestrator.chat",
        payload={
            "message": "hi T",
            "session_id": session_id,
            "response_channel": response_channel,
        },
        priority=Priority.NORMAL,
        metadata={"session_id": session_id},
    )
    
    print(f"\n1. SENDING MESSAGE")
    print(f"   correlation_id: {correlation_id}")
    print(f"   message_id: {message.message_id}")
    print(f"   target stream: aegis:stream:torchestrator")
    print(f"   payload: {message.payload}")
    
    # Publish to TOrchestrator stream
    entry_id = await redis.xadd(
        "aegis:stream:torchestrator",
        {"data": message.model_dump_json()},
        maxlen=10000,
        approximate=True
    )
    print(f"   ✓ Published to aegis:stream:torchestrator (entry_id: {entry_id})")
    
    # Now trace what happens - monitor the streams
    print(f"\n2. MONITORING STREAMS FOR RESPONSE...")
    print(f"   Listening on: {response_channel} (group: {consumer_group})")
    
    # Wait for response with timeout
    timeout_at = asyncio.get_event_loop().time() + 60
    response_received = False
    
    while asyncio.get_event_loop().time() < timeout_at:
        # Check response channel
        messages = await redis.xreadgroup(
            groupname=consumer_group,
            consumername="cli-tracer",
            streams={response_channel: ">"},
            count=1,
            block=1000,
        )
        
        if messages:
            for stream_name, entries in messages:
                for entry_id, fields in entries:
                    raw_data = fields.get("data")
                    if raw_data:
                        try:
                            parsed = json.loads(raw_data)
                            resp_msg = AegisMessage.model_validate(parsed)
                            
                            print(f"\n3. RESPONSE RECEIVED")
                            print(f"   Stream: {stream_name}")
                            print(f"   Entry ID: {entry_id}")
                            print(f"   correlation_id: {resp_msg.correlation_id}")
                            print(f"   source_agent: {resp_msg.source_agent}")
                            print(f"   target_agent: {resp_msg.target_agent}")
                            print(f"   message_type: {resp_msg.message_type}")
                            print(f"   action: {resp_msg.action}")
                            print(f"   payload keys: {list(resp_msg.payload.keys())}")
                            
                            if "response" in resp_msg.payload:
                                print(f"   Response: {resp_msg.payload['response'][:200]}...")
                            
                            if "metadata" in resp_msg.payload:
                                meta = resp_msg.payload["metadata"]
                                print(f"   Metadata: latency_ms={meta.get('latency_ms')}, tools={meta.get('tools_used')}, skills={meta.get('skills_used')}, intent={meta.get('intent_category')}")
                            
                            # Acknowledge
                            await redis.xack(stream_name, consumer_group, str(entry_id))
                            response_received = True
                            
                        except Exception as e:
                            print(f"   Error parsing response: {e}")
                            await redis.xack(stream_name, consumer_group, str(entry_id))
        
        # Also check what's in the torchestrator stream (pending/processing)
        if not response_received:
            # Check intermediate streams to trace flow
            streams_to_check = [
                "aegis:stream:torchestrator",
                "aegis:stream:oracle",
                "aegis:stream:forge",
                "aegis:stream:warden",
                "aegis:stream:lexicon",
                "aegis:stream:identity",
                "aegis:stream:janus",
            ]
            
            for stream in streams_to_check:
                try:
                    # Check pending messages for our correlation_id
                    group_name = f"aegis:group:{stream.split(':')[-1]}"
                    pending = await redis.xpending_range(
                        stream, 
                        group_name, 
                        min="-", 
                        max="+", 
                        count=10
                    )
                    if pending:
                        for p in pending:
                            # Check if this is our message
                            entries = await redis.xrange(stream, min=p["message_id"], max=p["message_id"], count=1)
                            for eid, fields in entries:
                                data = fields.get("data")
                                if data and correlation_id in data:
                                    print(f"   📍 Found correlation_id {correlation_id[:8]}... in {stream} (pending: {p['consumer']}, idle: {p['time_since_delivered']}ms)")
                except Exception:
                    pass  # Stream or group might not exist
        
        if response_received:
            break
        
        await asyncio.sleep(0.5)
    
    if not response_received:
        print(f"\n❌ TIMEOUT: No response received within 60 seconds")
    
    # Check final stream states
    print(f"\n4. FINAL STREAM STATE CHECK")
    for stream in [
        "aegis:stream:torchestrator",
        "aegis:stream:oracle", 
        "aegis:stream:forge",
        "aegis:stream:warden",
        response_channel,
    ]:
        try:
            info = await redis.xinfo_stream(stream)
            groups = await redis.xinfo_groups(stream)
            print(f"   {stream}: length={info['length']}, groups={len(groups)}")
            for g in groups:
                print(f"     Group: {g['name']}, consumers={g['consumers']}, pending={g['pending']}")
        except Exception as e:
            print(f"   {stream}: Not found or error: {e}")
    
    await redis.close()
    print(f"\n{'='*80}")
    print(f"TRACE COMPLETE")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(trace_chat_message())