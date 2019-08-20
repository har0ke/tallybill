from datetime import datetime

import pytz
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Transform, F
from django.db.models.base import ModelBase
from django.db.models.query_utils import Q
from django.db.models.signals import post_save
from django.dispatch import receiver

from tallybill import settings


def datetime_now_tz():
    return datetime.now(tz=pytz.timezone(settings.TIME_ZONE))


def date_now():
    return datetime_now_tz().date()


def FilteredManager(query):

    class _FilteredManager(models.Manager):

        def get_queryset(self):
            return super(_FilteredManager, self).get_queryset().filter(query)
    return _FilteredManager()


class CustomMeta(ModelBase):
    """
    def __new__(cls, name, bases, attr):

        def prop_gen(field_name):
            def prop(self):
                return getattr(self, '%s_original' % field_name) != getattr(self, field_name)

            return property(prop)

        add_attr = {}
        if "track_fields" in attr:
            for field in attr["track_fields"]:
                add_attr[field + "_changed"] = prop_gen(field)
        return super(CustomMeta, cls).__new__(cls, name, bases, attr)
    """


class BaseModelMixin(metaclass=CustomMeta):
    pass


class FieldTrackerMixin(object):

    track_fields = []

    def __init__(self, *args, **kwargs):
        assert isinstance(self, models.Model) and isinstance(self, FieldTrackerMixin)

        super(FieldTrackerMixin, self).__init__(*args, **kwargs)

        def prop_gen(field_name):
            def prop(me):
                return getattr(me, '%s_original' % field_name) != getattr(me, field_name)
            return property(prop)

        for field in self.track_fields:
            setattr(self, '%s_original' % field, getattr(self, field))
            # TODO: do this in meta...
            setattr(self.__class__, field + "_changed", prop_gen(field))


class InvoiceDependencies(object):
    def get_related_invoices(self):
        raise NotImplementedError()

    def set_may_have_changed(self, kwargs):
        inventory_ids = set([i.pk for i in self.get_related_invoices() if i])
        Inventory.objects.filter(pk__in=inventory_ids, may_have_changed=False).update(may_have_changed=True)

    def delete(self, *args, **kwargs):
        assert isinstance(self, models.Model) and isinstance(self, InvoiceDependencies)
        set_may_have_changed = "fast" not in kwargs or not kwargs.pop("fast")
        ret = super(InvoiceDependencies, self).delete(*args, **kwargs)
        if set_may_have_changed:
            self.set_may_have_changed(kwargs)
        return ret

    def save(self, *args, **kwargs):
        assert isinstance(self, models.Model) and isinstance(self, InvoiceDependencies)
        set_may_have_changed = "fast" not in kwargs or not kwargs.pop("fast")
        ret = super(InvoiceDependencies, self).save(*args, **kwargs)
        if set_may_have_changed:
            self.set_may_have_changed(kwargs)
        return ret


class UserExtension(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    allow_login = models.BooleanField(default=True)

    def display_name(self):
        if self.user.first_name:
            return self.user.last_name + ", " + self.user.first_name
        else:
            return self.user.username

    def __str__(self):
        return str(self.user)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserExtension.objects.create(user=instance, )


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    pass
    # instance.account.save()


class ProductType(models.Model):
    name = models.CharField(max_length=200)

    def __str__(self):
        return "<ProductType: %s>" % self.name


class Product(models.Model):
    product_type = models.ForeignKey(ProductType, on_delete=models.SET_NULL, blank=True, null=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return "<Product: %s>" % self.name


class Inventory(InvoiceDependencies, models.Model, FieldTrackerMixin):
    track_fields = ["date"]
    date = models.DateField(default=date_now, unique=True)
    may_have_changed = models.BooleanField(default=True)

    def get_related_invoices(self):
        next_inventory = Inventory.get_next_inventory_by_date(self.date, True)
        return (([Inventory.get_next_inventory_by_date(self.date_original, True)] if self.date_changed else []) +
                [self, next_inventory])

    @staticmethod
    def get_next_inventory_by_date(d, eq=True):
        try:
            if eq:
                return Inventory.objects.filter(date__gte=d).order_by("date").first()
            else:
                return Inventory.objects.filter(date__gt=d).order_by("date").first()
        except Inventory.DoesNotExist:
            pass

    @staticmethod
    def get_prev_inventory_by_date(d):
        try:
            return Inventory.objects.filter(date__lt=d).order_by("-date").first()
        except Inventory.DoesNotExist:
            pass


class ProductInventory(InvoiceDependencies, models.Model, FieldTrackerMixin):
    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    count = models.IntegerField()

    track_fields = ["inventory"]

    def get_related_invoices(self):
        return ((self.inventory.get_related_invoices() if self.inventory_changed else []) +
                self.inventory_original.get_related_invoices())


class IncomingInvoice(InvoiceDependencies, FieldTrackerMixin, models.Model):
    # to verify every invoice is input correctly
    date = models.DateField(default=date_now)
    invoice_id = models.CharField(max_length=200)

    track_fields = ["date"]

    def get_related_invoices(self):
        return (([Inventory.get_next_inventory_by_date(self.date_original, True)] if self.date_changed else []) +
                [Inventory.get_next_inventory_by_date(self.date, True)])


class Order(InvoiceDependencies, models.Model, FieldTrackerMixin):
    incoming_invoice = models.ForeignKey(IncomingInvoice, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    each_cents = models.IntegerField()
    count = models.IntegerField()

    track_fields = ["incoming_invoice"]

    def __str__(self):
        return "<Order: %s - %d>" % (self.product.name, self.count)

    def get_related_invoices(self):
        return ((self.incoming_invoice_original.get_related_invoices() if self.incoming_invoice_changed else []) +
                self.incoming_invoice.get_related_invoices())


class Consumption(InvoiceDependencies, models.Model, FieldTrackerMixin):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    count = models.PositiveIntegerField()
    date = models.DateField(default=date_now)
    issued_by = models.ForeignKey(User, on_delete=models.CASCADE,
                                  related_name="issued_consumption")
    track_fields = ["date"]

    def __str__(self):
        return "<Consumption: %s - %s - %d>" % (self.user.username, self.product.name, self.count)

    def get_related_invoices(self):
        return ((Inventory.get_next_inventory_by_date(self.date_original, True) if self.date_changed else []) +
                [Inventory.get_next_inventory_by_date(self.date, True)])


class OutgoingInvoice(models.Model):
    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE)
    # OutgoingInvoice.date: the date invoice was issued
    # use inventory.date for billing period
    date = models.DateTimeField(default=datetime_now_tz)
    total = models.IntegerField(default=0)
    profit = models.IntegerField(default=0)

    is_frozen = models.BooleanField(default=False)
    correction_of = models.OneToOneField("main.OutgoingInvoice", null=True, blank=True, related_name="corrected_by",
                                         on_delete=models.CASCADE, default=None)

    objects = FilteredManager((Q(corrected_by=None) | Q(corrected_by__is_frozen=False)) & Q(is_frozen=True))
    objects_all = models.Manager()
    objects_initial = FilteredManager(Q(correction_of=None, is_frozen=True))
    objects_temporary = FilteredManager(Q(is_frozen=False))
    objects_latest = FilteredManager(Q(is_frozen=True) & (Q(corrected_by=None) | Q(corrected_by__is_frozen=False)))

    @property
    def diff_euro(self):
        if self.correction_of:
            return (self.total - self.correction_of.total) / 100.
        else:
            return self.total / 100.

    @property
    def total_euro(self):
        return self.total / 100.

    def correction_of_iterator(self):
        invoice = self.correction_of
        while invoice:
            yield invoice
            invoice = invoice.correction_of

    def corrected_by_iterator(self):
        invoice = self
        while invoice:
            try:
                invoice = invoice.corrected_by
            except OutgoingInvoice.DoesNotExist:
                return None
            yield invoice

    @property
    def is_temporary(self):
        return not self.is_frozen

    def __str__(self):
        return str(self.inventory.date)

    @property
    def differences_to_approve(self):
        return (not self.is_frozen and
                (self.correction_of_id is None or
                (self.total != self.correction_of.total and
                self.correction_of.is_frozen)))

    @staticmethod
    def get_to_approve_differences():
        return OutgoingInvoice.objects_all.filter(
            ~Q(total=F("correction_of__total")) & Q(correction_of__is_frozen=True, is_frozen=False))


class OutgoingInvoiceProductPosition(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    invoice = models.ForeignKey(OutgoingInvoice, on_delete=models.CASCADE)
    loss = models.FloatField()
    price_each = models.IntegerField()
    total = models.IntegerField()
    profit = models.IntegerField()

    def __str__(self):
        return str(self.invoice.inventory.date) + " - " + self.product.name


class OutgoingInvoiceProductUserPosition(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    productinvoice = models.ForeignKey(OutgoingInvoiceProductPosition, on_delete=models.CASCADE)
    count = models.IntegerField()


