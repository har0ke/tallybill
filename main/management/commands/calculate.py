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
        parser.add_argument("--all", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        print(options["all"])
        if options["all"]:
            inventories = Inventory.objects.all()
        else:
            inventories = Inventory.objects.filter(may_have_changed=True)

        print(inventories)

        begin = datetime.now()

        for inventory in inventories:
            BillingPeriod(inventory).recalculate_temporary_invoices()

        diff = datetime.now() - begin
        print(diff)
        print([i.date for i in
               Inventory.objects.filter(may_have_changed=True)])

