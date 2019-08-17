#!/usr/bin/python
# -*- coding: <utf-8> -*-
import csv
import os
from datetime import date, datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F
from django.db.models.aggregates import Sum
from django.db.models.functions import Cast
from django.forms import FloatField
from os import makedirs

from main.billing import BillingPeriod, outgoing_to_csv
from main.models import Inventory, OutgoingInvoice, OutgoingInvoiceProductUserPosition


class Command(BaseCommand):
    """
    imports Getraenke.xlsx into database. clean database required.
    """
    def add_arguments(self, parser):
        # declare file to import from
        parser.add_argument("-output_dir", default="output")
        parser.add_argument("-invoice")

    def export(self, outgoing, options):

        positions = OutgoingInvoiceProductUserPosition.objects \
            .filter(productinvoice__invoice=outgoing).values_list("user__username") \
            .annotate(total=Sum(F("count") * F("productinvoice__price_each"))).order_by("user__username")

        with open(os.path.join(options["output_dir"],
                               datetime.strftime(outgoing.inventory.date, "%Y-%m-%d.csv")),
                  "w", encoding="utf-8", newline="\n") as f:
            outgoing_to_csv(outgoing, f)

    @transaction.atomic
    def handle(self, *args, **options):
        if not os.path.exists(options["output_dir"]):
            makedirs(options["output_dir"])

        if "invoice" in options and options["invoice"]:
            invoices = [OutgoingInvoice.objects.get(inventory__date=datetime.strptime(options["invoice"], "%Y-%m-%d"))]
        else:
            invoices = OutgoingInvoice.objects.all()
        for outgoing in invoices:
            self.export(outgoing, options )