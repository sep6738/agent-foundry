"""SQLite-backed LangGraph checkpointer for durable interrupt/resume support."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
)
from sqlalchemy import delete, select

from agent_backend.app.storage.database import Database
from agent_backend.app.storage.models import GraphCheckpoint, GraphCheckpointWrite, new_id


class DatabaseCheckpointer(BaseCheckpointSaver):
    """Persists checkpoints and pending writes in the project SQLite database."""

    def __init__(self, db: Database, *, serde=None) -> None:
        super().__init__(serde=serde)
        self.db = db

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)
        with self.db.session() as session:
            query = select(GraphCheckpoint).where(
                GraphCheckpoint.thread_id == thread_id,
                GraphCheckpoint.checkpoint_ns == checkpoint_ns,
            )
            if checkpoint_id:
                query = query.where(GraphCheckpoint.checkpoint_id == checkpoint_id)
            else:
                query = query.order_by(GraphCheckpoint.created_at.desc()).limit(1)
            row = session.scalars(query).first()
            if row is None:
                return None
            checkpoint = self.serde.loads_typed((row.type, row.payload))
            metadata = self.serde.loads_typed((row.metadata_type, row.metadata_blob))
            write_rows = session.scalars(
                select(GraphCheckpointWrite)
                .where(
                    GraphCheckpointWrite.thread_id == thread_id,
                    GraphCheckpointWrite.checkpoint_ns == checkpoint_ns,
                    GraphCheckpointWrite.checkpoint_id == row.checkpoint_id,
                )
                .order_by(GraphCheckpointWrite.task_id, GraphCheckpointWrite.idx)
            ).all()
            pending_writes = [
                (
                    write.task_id,
                    write.channel,
                    self.serde.loads_typed((write.type, write.payload)),
                )
                for write in write_rows
            ]
            parent_config = None
            if row.parent_checkpoint_id:
                parent_config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": row.parent_checkpoint_id,
                    }
                }
            return CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": row.checkpoint_id,
                    }
                },
                checkpoint=checkpoint,
                metadata=metadata,
                pending_writes=pending_writes,
                parent_config=parent_config,
            )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        thread_id = config["configurable"]["thread_id"] if config else None
        checkpoint_ns = config["configurable"].get("checkpoint_ns") if config else None
        before_id = get_checkpoint_id(before) if before else None
        with self.db.session() as session:
            query = select(GraphCheckpoint)
            if thread_id is not None:
                query = query.where(GraphCheckpoint.thread_id == thread_id)
            if checkpoint_ns is not None:
                query = query.where(GraphCheckpoint.checkpoint_ns == checkpoint_ns)
            query = query.order_by(GraphCheckpoint.created_at.desc())
            for row in session.scalars(query):
                if before_id and row.checkpoint_id >= before_id:
                    continue
                checkpoint = self.serde.loads_typed((row.type, row.payload))
                metadata = self.serde.loads_typed((row.metadata_type, row.metadata_blob))
                if filter and not all(metadata.get(key) == value for key, value in filter.items()):
                    continue
                parent_config = None
                if row.parent_checkpoint_id:
                    parent_config = {
                        "configurable": {
                            "thread_id": row.thread_id,
                            "checkpoint_ns": row.checkpoint_ns,
                            "checkpoint_id": row.parent_checkpoint_id,
                        }
                    }
                yield CheckpointTuple(
                    config={
                        "configurable": {
                            "thread_id": row.thread_id,
                            "checkpoint_ns": row.checkpoint_ns,
                            "checkpoint_id": row.checkpoint_id,
                        }
                    },
                    checkpoint=checkpoint,
                    metadata=metadata,
                    pending_writes=[],
                    parent_config=parent_config,
                )
                if limit is not None:
                    limit -= 1
                    if limit <= 0:
                        break

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")
        checkpoint_type, checkpoint_payload = self.serde.dumps_typed(checkpoint)
        metadata_type, metadata_payload = self.serde.dumps_typed(metadata)
        with self.db.transaction() as session:
            session.execute(
                delete(GraphCheckpoint).where(
                    GraphCheckpoint.thread_id == thread_id,
                    GraphCheckpoint.checkpoint_ns == checkpoint_ns,
                    GraphCheckpoint.checkpoint_id == checkpoint["id"],
                )
            )
            session.add(
                GraphCheckpoint(
                    id=new_id("chk"),
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=checkpoint["id"],
                    parent_checkpoint_id=parent_checkpoint_id,
                    type=checkpoint_type,
                    payload=checkpoint_payload,
                    metadata_type=metadata_type,
                    metadata_blob=metadata_payload,
                )
            )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]
        with self.db.transaction() as session:
            for idx, (channel, value) in enumerate(writes):
                write_idx = WRITES_IDX_MAP.get(channel, idx)
                value_type, value_payload = self.serde.dumps_typed(value)
                session.execute(
                    delete(GraphCheckpointWrite).where(
                        GraphCheckpointWrite.thread_id == thread_id,
                        GraphCheckpointWrite.checkpoint_ns == checkpoint_ns,
                        GraphCheckpointWrite.checkpoint_id == checkpoint_id,
                        GraphCheckpointWrite.task_id == task_id,
                        GraphCheckpointWrite.idx == write_idx,
                    )
                )
                session.add(
                    GraphCheckpointWrite(
                        id=new_id("wr"),
                        thread_id=thread_id,
                        checkpoint_ns=checkpoint_ns,
                        checkpoint_id=checkpoint_id,
                        task_id=task_id,
                        idx=write_idx,
                        channel=channel,
                        type=value_type,
                        payload=value_payload,
                        task_path=task_path,
                    )
                )

    def delete_thread(self, thread_id: str) -> None:
        with self.db.transaction() as session:
            session.execute(
                delete(GraphCheckpointWrite).where(GraphCheckpointWrite.thread_id == thread_id)
            )
            session.execute(delete(GraphCheckpoint).where(GraphCheckpoint.thread_id == thread_id))
