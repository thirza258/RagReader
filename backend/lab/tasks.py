"""Background execution of evaluation experiments (PRD §29)."""
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from lab.services import runner

logger = logging.getLogger(__name__)


@shared_task(bind=True, soft_time_limit=3600, time_limit=3660)
def run_experiment_task(self, experiment_id, token):
    """Run (or resume) one experiment. A duplicate delivery or stale token does nothing."""
    try:
        return runner.run_experiment(experiment_id, token)
    except SoftTimeLimitExceeded:
        logger.warning("Experiment %s hit the worker time limit", experiment_id)
        runner.fail_timeout(experiment_id, token)
        return False
