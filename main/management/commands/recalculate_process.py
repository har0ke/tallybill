#!/usr/bin/python
# -*- coding: <utf-8> -*-

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from main.billing import RecalculateThread
from main.models import ProductType


class Command(BaseCommand):

    @transaction.atomic
    def handle(self, *args, **options):
        r_thread = RecalculateThread()
        r_thread.start()
        try:
            r_thread.join()
        except KeyboardInterrupt:
            r_thread.running = False
        r_thread.join()