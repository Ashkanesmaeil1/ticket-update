# -*- coding: utf-8 -*-
"""
Management command to send task deadline reminder emails.

Logic (in services.run_task_deadline_reminders):
- When 7.5 < remaining <= 8.5 hours: send one "8 hours left" email (only once per task).
- When 1.5 < remaining <= 2.5 hours: send one "2 hours left" email (only once per task).

Reminders are also sent automatically by the in-app scheduler while the server is running.
This command is still useful for manual runs or when using a separate cron/scheduler.
"""
from django.core.management.base import BaseCommand
from tickets.services import run_task_deadline_reminders


class Command(BaseCommand):
    help = (
        'Send deadline reminder emails for ticket tasks: 8h and 2h before deadline. '
        'Also runs automatically in the app every minute when the server is running.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only log what would be sent, do not send emails or update flags.',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        sent_8h, sent_2h = run_task_deadline_reminders(dry_run=dry_run)
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f'[dry-run] Would send 8h: {sent_8h}, 2h: {sent_2h}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Done. Sent 8h: {sent_8h}, 2h: {sent_2h}'))
