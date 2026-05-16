"""arq worker entrypoint.

Run with: `arq app.tasks.worker.WorkerSettings`.

Cron jobs are registered here; one-shot jobs are enqueued from request handlers
with `await arq_pool.enqueue_job("name", ...)`.
"""

from datetime import UTC, datetime

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.database import session_scope
from app.core.logging import configure_logging, get_logger
from app.services import subscription as sub_svc
from app.tasks import payment_reminders

configure_logging()
log = get_logger("worker")


async def startup(ctx):  # noqa: ANN001
    log.info("worker.startup")


async def shutdown(ctx):  # noqa: ANN001
    log.info("worker.shutdown")


async def task_check_grace_period(ctx) -> int:  # noqa: ANN001
    async with session_scope() as db:
        n = await sub_svc.suspend_if_grace_expired(db)
    log.info("task.grace_period.swept", suspended=n)
    return n


async def task_send_payment_reminders(ctx) -> int:  # noqa: ANN001
    async with session_scope() as db:
        return await payment_reminders.dispatch_due_reminders(db, now=datetime.now(UTC))


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(str(settings.redis_url))
    on_startup = startup
    on_shutdown = shutdown
    functions = [task_check_grace_period, task_send_payment_reminders]
    cron_jobs = [
        # Hourly sweep — keep cheap.
        cron(task_check_grace_period, hour=set(range(24)), minute={5}),
        # Daily 09:00 UTC reminder run.
        cron(task_send_payment_reminders, hour={9}, minute={0}),
    ]
