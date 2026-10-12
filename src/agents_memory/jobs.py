from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic

from .application import Application
from .domain import DomainError, JobLease
from .lexical import tokens


@dataclass
class LeaseFrame:
    current: JobLease
    failure: DomainError | None = None


class Worker:
    def __init__(self, application: Application) -> None:
        self.application = application
        self._stop = asyncio.Event()
        self.current_job: str | None = None
        self._task: asyncio.Task | None = None
        self.queue_error: str | None = None
        self.last_job_error: str | None = None

    @property
    def status(self) -> dict:
        running = self._task is not None and not self._task.done()
        return {
            "running": running,
            "queue_error": self.queue_error,
            "last_job_error": self.last_job_error,
            "active_job": self.current_job,
        }

    def start(self) -> None:
        self._task = asyncio.create_task(self.run(), name="agents-memory-worker")

    async def _pulse(self, frame: LeaseFrame, finished: asyncio.Event) -> None:
        interval = self.application.settings.heartbeat_seconds
        deadline = monotonic() + max(0, (frame.current.deadline - datetime.now(UTC)).total_seconds())
        while not finished.is_set():
            remaining = deadline - monotonic()
            if remaining <= 0:
                frame.failure = DomainError("LEASE_STALE", "The confirmed worker lease deadline elapsed")
                return
            try:
                await asyncio.wait_for(finished.wait(), min(interval, remaining))
            except TimeoutError:
                if finished.is_set():
                    return
                remaining = deadline - monotonic()
                if remaining <= 0:
                    frame.failure = DomainError("LEASE_STALE", "The confirmed worker lease deadline elapsed")
                    return
                try:
                    frame.current = await asyncio.wait_for(self.application.store.heartbeat(frame.current), remaining)
                except DomainError as error:
                    if error.code not in {"DELETION_BARRIER", "DATABASE_UNAVAILABLE"}:
                        frame.failure = error
                        return
                except Exception:
                    # An unavailable heartbeat is not proof of lost ownership. Only
                    # a confirmed renewal extends this monotonic retry deadline.
                    continue
                else:
                    deadline = monotonic() + max(0, (frame.current.deadline - datetime.now(UTC)).total_seconds())

    async def _process(self, lease: JobLease) -> None:
        frame = LeaseFrame(lease)
        finished = asyncio.Event()
        pulse = asyncio.create_task(self._pulse(frame, finished), name="agents-memory-lease-heartbeat")
        failure: str | None = None
        blocked = False
        result = None
        admission = None
        vectors = None
        lexical_rows = None
        try:
            purpose = {"extract": "extraction", "consolidate": "consolidation", "reflect": "reflection", "reindex": "embedding"}[lease.kind]
            runtime = self.application.model(purpose)
            if lease.kind == "extract":
                self.application.model("embedding")
            admission = await self.application.store.admit_job(frame.current, runtime.revision, purpose)
            if lease.kind == "extract":
                sources = await self.application.store.admitted_sources(admission)
                if len(sources) != 1:
                    raise DomainError("JOB_INPUT_INVALID", "Extraction requires exactly its admitted source")
                result = await runtime.extract(sources[0])
                vectors = await runtime.embed(tuple(claim.statement for claim in result.claims))
                lexical_rows = [tokens(" ".join((c.statement, c.subject, c.predicate, c.object, *c.entities))) for c in result.claims]
            elif lease.kind == "consolidate":
                claims = await self.application.store.admitted_claims(admission)
                result = await runtime.consolidate(claims)
            elif lease.kind == "reindex":
                claims = await self.application.store.admitted_claims(admission)
                vectors = await runtime.embed(tuple(claim.draft.statement for claim in claims))
                lexical_rows = [
                    tokens(" ".join((claim.draft.statement, claim.draft.subject, claim.draft.predicate,
                                     claim.draft.object, *claim.draft.entities)))
                    for claim in claims
                ]
            else:
                claims = await self.application.store.admitted_claims(admission)
                sources = await self.application.store.admitted_sources(admission)
                query = next((source for source in sources if source.id == lease.query_source_id), None)
                if query is None:
                    raise DomainError("JOB_INPUT_INVALID", "Reflection requires its admitted query source")
                result = await runtime.reflect(query.body, claims)
        except DomainError as error:
            failure = error.code
            blocked = error.code in {"MODEL_ROUTE_BLOCKED", "SERVICE_DRAINING"}
        except Exception:
            failure = "JOB_EXECUTION_FAILED"
        finally:
            finished.set()
            await pulse
        if frame.failure is not None:
            failure = frame.failure.code
        try:
            if failure is not None:
                await self.application.store.fail_job(frame.current, failure, blocked)
                self.last_job_error = failure
                return
            if lease.kind == "extract":
                await self.application.store.publish_extraction(
                    frame.current, admission, result, vectors, lexical_rows
                )
            elif lease.kind == "consolidate":
                await self.application.store.publish_consolidation(frame.current, admission, result)
            elif lease.kind == "reindex":
                await self.application.store.publish_reindex(frame.current, admission, vectors, lexical_rows)
            else:
                await self.application.store.publish_reflection(frame.current, admission, result)
        except DomainError as error:
            self.last_job_error = error.code
            try:
                await self.application.store.fail_job(frame.current, error.code)
            except DomainError:
                return
        except Exception:
            self.last_job_error = "JOB_PUBLICATION_UNAVAILABLE"

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                lease = await self.application.store.claim_job()
                self.queue_error = None
            except Exception:
                lease = None
                self.queue_error = "QUEUE_AUTHORITY_UNAVAILABLE"
            if lease is None:
                try:
                    await asyncio.wait_for(self._stop.wait(), 0.5)
                except TimeoutError:
                    continue
                break
            self.current_job = lease.job_id
            try:
                await self._process(lease)
            except Exception:
                self.last_job_error = "WORKER_PROCESS_FAILED"
            finally:
                self.current_job = None

    async def stop(self, timeout: float = 30) -> dict:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout)
            except TimeoutError:
                return {"local_drained": False, "active_job": self.current_job, "durable_work_recoverable": True}
        return {"local_drained": True, "active_job": None, "durable_work_recoverable": True}
