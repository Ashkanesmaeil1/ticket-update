import os
import sys
import threading
import time

from django.apps import AppConfig


def _deadline_reminder_loop():
    """Background loop: every 60 seconds run task deadline reminders (8h and 2h emails)."""
    # Short delay so server and DB are ready
    time.sleep(30)
    from tickets.services import run_task_deadline_reminders
    import logging
    logger = logging.getLogger(__name__)
    while True:
        try:
            run_task_deadline_reminders(dry_run=False)
        except Exception as e:
            logger.exception('Task deadline reminder scheduler error: %s', e)
        time.sleep(60)


class TicketsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tickets'

    def ready(self):
        """Import signals and start automatic deadline reminder scheduler."""
        import tickets.signals  # noqa

        # Start reminder thread only in the process that actually runs the app
        # (not in runserver's file-watcher parent process)
        if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') != 'true':
            return
        thread = threading.Thread(target=_deadline_reminder_loop, daemon=True)
        thread.start()



