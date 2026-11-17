"""Background execution of research tasks (PRD §47)."""
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from research.services import runner

logger = logging.getLogger(__name__)


@shared_task(bind=True, soft_time_limit=900, time_limit=960)
def run_research_task(self, task_id, token):
    """Run one research task. A duplicate delivery or stale token does nothing."""
    try:
        return runner.run_task(task_id, token)
    except SoftTimeLimitExceeded:
        logger.warning("Research task %s hit the worker time limit", task_id)
        runner.fail_timeout(task_id, token)
        return False
