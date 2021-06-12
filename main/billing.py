import csv
import math
import time
import traceback
from datetime import datetime
from sqlite3 import OperationalError

from django.db import transaction, OperationalError
from django.db.backends import sqlite3
from django.db.models import F
from django.db.models.aggregates import Sum
from django.db.models.query_utils import Q
from threading import Thread

import numpy

from main.models import Consumption, Order, Inventory, Product, OutgoingInvoice, \
    OutgoingInvoiceProductPosition, OutgoingInvoiceProductUserPosition, ProductInventory
from tallybill.tally_settings import PROFIT_FACTOR, PROFIT_FIXED_CENTS


def _get_total_consumption_until(product, date):
    # total consumption of all recorded data, including loss
    inventory_count = 0
    try:
        inventory_count = ProductInventory.objects.get(inventory__date=date, product=product).count
    except ProductInventory.DoesNotExist as e:
        pass
    orders_until = (Order.objects.filter(product=product, incoming_invoice__date__lte=date)
                    .aggregate(Sum("count"))["count__sum"] or 0)
    return orders_until - inventory_count


class BillingPeriod(object):

    def __init__(self, inventory, previous_inventory=None):
        # if inventory is None: nothing to inventory - a total of zero products are assumed
        self._inventory = inventory
        self._previous_inventory = previous_inventory
        if inventory is not None and previous_inventory is None:
            previous_inventories = Inventory.objects.filter(date__lt=inventory.date).order_by("-date")
            if previous_inventories.count() > 0:
                self._previous_inventory = previous_inventories.first()

    @property
    def inventory(self):
        return self._inventory

    @property
    def products(self):
        query = Q(productinventory__inventory=self._inventory)
        if self._previous_inventory is not None:
            query |= Q(productinventory__inventory=self._previous_inventory)
        return [ProductInPeriod(self, p) for p in Product.objects.filter(query).distinct()]

    @property
    def date_from(self):
        if self._previous_inventory:
            return self._previous_inventory.date
        # just some random time long ago
        return None

    @property
    def date_until(self):
        return self._inventory.date

    @property
    def previous_billing_period(self):
        if self._previous_inventory:
            return BillingPeriod(self._previous_inventory)
        return None

    @staticmethod
    def all():
        return (BillingPeriod(inventory) for inventory in Inventory.objects.all())

    @property
    def invoices(self):
        return OutgoingInvoice.objects_all.filter(inventory=self._inventory).order_by("date")

    @transaction.atomic
    def recalculate_temporary_invoices(self):
        # there should always only be one temporary invoice
        try:
            invoice = self.invoices.get(is_frozen=False)
        except OutgoingInvoice.DoesNotExist:
            try:
                correction_of = self._inventory.outgoinginvoice_set.get()
            except OutgoingInvoice.DoesNotExist:
                correction_of = None
            invoice = OutgoingInvoice(inventory=self._inventory, correction_of=correction_of)
            invoice.save()
        invoice.outgoinginvoiceproductposition_set.all().delete()

        # recalculate shit
        invoice_total = 0
        invoice_profit = 0
        for product in self.products:
            pos_loss_factor = float(max(1.0, product.get_loss_factor()))
            avg_price = product.get_avg_price_for_consumed()
            if pos_loss_factor == math.inf:
                each_cents = 0
                each_no_profit = 0
            else:
                each_cents = int(avg_price * pos_loss_factor * PROFIT_FACTOR + PROFIT_FIXED_CENTS)
                each_no_profit = int(avg_price * pos_loss_factor)

            position = OutgoingInvoiceProductPosition.objects.create(
                product=product.product, invoice=invoice,
                loss=product.get_loss(), price_each=each_cents, total=0, profit=0)
            product_total = 0
            for user, count in product.get_user_consumptions():
                product_total += count
                OutgoingInvoiceProductUserPosition.objects.create(user_id=user, count=count, productinvoice=position)
            invoice_total += product_total * each_cents
            invoice_profit += product_total * each_cents - product_total * each_no_profit
            position.total = product_total * each_cents
            position.profit = product_total * each_cents - product_total * each_no_profit
            position.save()

        invoice.total = invoice_total
        invoice.profit = invoice_profit
        invoice.save()
        self._inventory.may_have_changed = False
        self._inventory.save(fast=True)


class ProductInPeriod(object):

    def __init__(self, billing_period, product):
        self._billing_period = billing_period
        self._product = product

    @property
    def product(self):
        return self._product

    @property
    def billing_period(self):
        return self._billing_period

    def get_total_orders(self):
        q = Q(incoming_invoice__date__lte=self._billing_period.date_until, product=self._product)
        if self._billing_period.date_from is not None:
            q &= Q(incoming_invoice__date__gt=self._billing_period.date_from)
        return Order.objects.filter(q).aggregate(Sum("count"))["count__sum"] or 0

    @staticmethod
    def get_total_orders_table(inventories_qs, product_qs):
        inventories = inventories_qs.values_list("pk", "date")
        product_ids = list(product_qs.values_list("pk", flat=True))
        orders = (Order.objects.values("incoming_invoice__date", "product")
                  .annotate(count=Sum("count")).order_by("incoming_invoice__date")
                  .values_list("incoming_invoice__date", "product", "count").iterator())
        table = numpy.zeros((inventories.count(), Product.objects.count()), dtype=int)

        try:
            order_date, order_product_id, count = next(orders)
            for i, (pk, date) in enumerate(inventories):
                    while order_date <= date:
                        table[i][product_ids.index(order_product_id)] += count
                        order_date, order_product_id, count = next(orders)
        except StopIteration:
            pass
        return table

    @staticmethod
    def get_product_inventory_count_table(inventories_qs, product_qs):
        # TODO what if inventories_qs is not all inventories ordered by date... fail
        inventories = list(inventories_qs.values_list("pk", flat=True))
        product_ids = list(product_qs.values_list("pk", flat=True))
        product_inventories = ProductInventory.objects.values_list("inventory", "product", "count")
        table = numpy.zeros((len(inventories), len(product_ids)), dtype=int)

        for inventory, product, count in product_inventories:
                table[inventories.index(inventory)][product_ids.index(product)] += count
        return table, inventories, product_ids

    @classmethod
    def get_real_consumption_list(cls, inventories_qs, product_qs):
        # TODO what if inventories_qs is not all inventories ordered by date... fail
        product_inventory_table, inventory_ids, product_ids = cls.get_product_inventory_count_table(inventories_qs, product_qs)
        product_order_table = cls.get_total_orders_table(inventories_qs, product_qs)

        result_table = numpy.zeros(product_order_table.shape, dtype=int)
        for inventory_idx in range(len(inventory_ids)):
            for product_idx in range(len(product_ids)):
                if inventory_idx > 0:
                    previous_inventory_count = product_inventory_table[inventory_idx - 1, product_idx]
                else:
                    previous_inventory_count = 0
                result_table[inventory_idx, product_idx] = (previous_inventory_count +
                                                            product_order_table[inventory_idx, product_idx] -
                                                            product_inventory_table[inventory_idx, product_idx])
        return result_table

    @staticmethod
    def get_listed_consumptions_table(inventories_qs, product_qs, consumptions=None):
        # TODO what if inventories_qs is not all inventories ordered by date... fail
        inventories = inventories_qs.values_list("pk", "date").order_by("date")
        product_ids = list(product_qs.values_list("pk", flat=True))

        consumptions_iter = ((Consumption.objects if consumptions is None else consumptions)
                             .values_list("date", "product_id", "count").order_by("date").iterator())

        table = numpy.zeros((inventories.count(), len(product_ids)), dtype=int)
        try:
            consumption_date, product_id, count = next(consumptions_iter)
            for i, (pk, date) in enumerate(inventories):
                while consumption_date <= date:
                    table[i][product_ids.index(product_id)] += count
                    consumption_date, product_id, count = next(consumptions_iter)
        except StopIteration:
            pass
        return table

    def get_real_consumption(self):
        assert isinstance(self._billing_period.inventory, Inventory)
        previous_inventory_count = 0
        if self._billing_period.previous_billing_period is not None:
            try:
                previous_inventory_count = (self._billing_period.previous_billing_period.inventory
                                            .productinventory_set.get(product=self._product).count)
            except ProductInventory.DoesNotExist as e:
                pass

        inventory_count = 0
        try:
            inventory_count = self._billing_period.inventory.productinventory_set.get(product=self._product).count
        except ProductInventory.DoesNotExist as e:
            pass

        consumption = (previous_inventory_count - inventory_count + self.get_total_orders())

        #  ------------------------ validating ---------------------------------
        # consumption2 = (_get_total_consumption_until(self._product, self._billing_period.date_until) -
        #                 _get_total_consumption_until(self._product, self._billing_period.date_from))
        # assert consumption == consumption2, (consumption, consumption2)
        # ------------------------- end valdiating -----------------------------

        return consumption

    def get_listed_consumptions(self):
        assert isinstance(self._product, Product)
        date_from = datetime.min if self._billing_period.date_from is None else self._billing_period.date_from
        return (self._product.consumption_set.filter(date__gt=date_from,
                                                     date__lte=self._billing_period.date_until)
                .aggregate(Sum("count"))["count__sum"] or 0)

    def get_avg_price_for_consumed(self):
        # avg price of products that where consumed
        # i assumed a product really is a single product
        # TODO bissl umstaendlich umgesetzt

        date_from = datetime.min if self._billing_period.date_from is None else self._billing_period.date_from
        consumed_before_period = _get_total_consumption_until(self._product, date_from)

        real_consumptions = max(self.get_real_consumption(), 0)
        remaining_consumptions = real_consumptions

        orders = self._product.order_set.order_by("incoming_invoice__date").values_list("count", "each_cents")
        if orders.count() == 0:
            quantities, prices = [], []
        else:
            quantities, prices = zip(*orders)
        quantities, prices = list(quantities), list(prices)
        # filter out all already billed quantities
        for i in range(len(quantities)):
            if consumed_before_period > 0:
                v = min(consumed_before_period, quantities[i])
                consumed_before_period -= v
                quantities[i] -= v
            if consumed_before_period == 0:
                v = min(quantities[i], remaining_consumptions)
                quantities[i] = v
                remaining_consumptions -= v

        assert(sum(quantities) == real_consumptions)
        if sum(quantities) == 0:
            return 0
        return sum([quantities[i] * prices[i] for i in range(len(prices))]) / sum(quantities)

    def get_loss_factor(self):
        # return factor to compensate loss
        real_consumptions = self.get_real_consumption()
        listed_consumptions = self.get_listed_consumptions()
        if listed_consumptions == 0:
            # loss cannot be compensated, since (apparently) nobody consumed nothing
            # (even though real_consumption may indicate consumptions)
            if real_consumptions != 0:
                return math.inf
            return 1.
        return real_consumptions / listed_consumptions

    def get_loss(self):
        lf = self.get_loss_factor()
        if lf > 0:
            return - (1. - lf) * 100.
        else:
            # negative real consumptions
            # loss not really interpretable
            # TODO: better options?
            return -math.inf

    def get_user_consumptions(self, user=None):
        date_from = datetime.min if self._billing_period.date_from is None else self._billing_period.date_from
        consumptions = Consumption.objects.filter(date__gt=date_from,
                                                  date__lte=self._billing_period.date_until, product=self._product)
        if user is not None:
            consumptions = consumptions.filter(user=user)

        return (consumptions.values("user").annotate(consumed=Sum("count"))
                .order_by("user").values_list("user", "consumed"))


class RecalculateThread(Thread):

    def __init__(self, *args, **kwargs):
        super(RecalculateThread, self).__init__(*args, **kwargs)
        self.running = True

    def run(self):
        print("Started Recalculation Thread.")
        while self.running:
            try:
                inventories = Inventory.objects.filter(may_have_changed=True)
                for inventory in inventories:
                    print("Recalculating: %s" % str(inventory))
                    BillingPeriod(inventory).recalculate_temporary_invoices()
            except OperationalError:
                pass
            except:
                traceback.print_exc()
            time.sleep(1.0)

        print("End Recalculation Thread.")

def outgoing_to_csv(outgoing, f, difference=False):

    def get_user_sum(outgoing_invoice):
        values = OutgoingInvoiceProductUserPosition.objects \
            .filter(productinvoice__invoice=outgoing_invoice).values_list("user__pk", "user__username") \
            .annotate(total=Sum(F("count") * F("productinvoice__price_each"))).order_by("user__username")
        return dict(((x, (y, z)) for x, y, z in values))

    def get_diff_positions():
        current_positions = get_user_sum(outgoing)

        if outgoing.correction_of is not None and difference:
            previous_positions = get_user_sum(outgoing.correction_of)
        else:
            previous_positions = {}

        updated_positions = [((current_positions[k][0], current_positions[k][1] - previous_positions[k][1])
                              if k in previous_positions else current_positions[k])
                             for k in current_positions]
        removed_positions = [(previous_positions[k][0], -previous_positions[k][1])
                             for k in set(previous_positions.keys()).difference(set(current_positions))]

        return updated_positions + removed_positions

    positions = get_diff_positions()

    writer = csv.writer(f)
    writer.writerow(["Datum", datetime.strftime(outgoing.inventory.date, "%d.%m.%Y")])
    writer.writerow(["Beschreibung", datetime.strftime(outgoing.inventory.date, "Getränkeabrechnung %B")])
    writer.writerow([])
    writer.writerow(["Account", "Wert (Positiv = belastend)", "Notizen"])

    sum = 0
    for name, amount in positions:
        writer.writerow([name, amount / 100.0])
        sum -= amount
    writer.writerow(["Getränke.Erträge", sum / 100.0])
    print(outgoing.inventory.date, sum / 100.)


import sys
is_runserver_command = False
for idx, value in enumerate(sys.argv):
    if value.endswith("manage.py"):
        is_runserver_command = sys.argv[idx + 1] == "runserver"
        break

if is_runserver_command:
    recalculate_thread = RecalculateThread()
    recalculate_thread.daemon = True
    recalculate_thread.start()

