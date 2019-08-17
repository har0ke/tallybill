#!/usr/bin/python
# -*- coding: <utf-8> -*-
from datetime import date, datetime
from django.core.management.base import BaseCommand
from django.db import transaction

from main.billing import BillingPeriod
from main.models import Inventory


class Command(BaseCommand):
    """
    imports Getraenke.xlsx into database. clean database required.
    """
    def add_arguments(self, parser):
        # declare file to import from
        parser.add_argument("invoice_date")

    @transaction.atomic
    def handle(self, *args, **options):
        print(options["invoice_date"])
        inv_date = datetime.strptime(options["invoice_date"], "%d.%m.%Y")

        inventory = Inventory.objects.get(
            date__year=inv_date.year,
            date__day=inv_date.day,
            date__month=inv_date.month)

        BillingPeriod(inventory).recalculate_temporary_invoices()
