#!/usr/bin/python
# -*- coding: <utf-8> -*-
import io
import json
import math
import urllib.parse
from datetime import date, datetime, timedelta
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import IntegrityError, models
from django.db.models import Max, Min, F
from django.db.models.aggregates import Sum
from django.db.models.query_utils import Q
from django.http import HttpResponseRedirect, HttpResponseNotFound, HttpResponseBadRequest
from django.http.response import HttpResponse
from django.shortcuts import render

# Create your views here.
import numpy

from main.billing import BillingPeriod, ProductInPeriod, outgoing_to_csv
from main.models import OutgoingInvoice, Product, Consumption, Inventory, \
    IncomingInvoice, ProductInventory, ProductType, OutgoingInvoiceProductPosition, Order, \
    OutgoingInvoiceProductUserPosition
from main.utils import parse_date, get_loss_color, get_inventory_dates, add_default_view_data, subtract_invoices, \
    get_invoice_data
from tallybill.tally_settings import TEMPLATE_BASE_URL


@staff_member_required
def admin_users(request):
    return render(request, 'admin/users.html', add_default_view_data(request, {
        "users": User.objects.all().order_by("username")
    }, "Admin - Users"))


@staff_member_required
def admin_user_edit(request, id_=None):
    return default_object_post(request, User, id_, "admin/user.html", {}, [
        ("username", "username", str),
        ("email", "email", str)
    ], lambda obj: "Admin - User: %s" % obj.username if obj.id else "Admin - New User",
        parent_page="/users/",  can_delete=lambda obj: False,
        pre_breadcrumbs=[(TEMPLATE_BASE_URL + "users", "Users")])

@staff_member_required
def admin_invoices_list(request):
    return render(request, "admin/invoice_list.html",   add_default_view_data(request, {
        "invoices":  (OutgoingInvoice.objects_temporary.all().order_by("-inventory__date"))
    }, "Admin - Invoices"))


@staff_member_required
def download_csv(request, pk):
    invoice = OutgoingInvoice.objects_all.get(pk=pk)
    buffer = io.StringIO()
    outgoing_to_csv(invoice, buffer, request.GET.get("difference") is not None)
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = ('attachment; filename=%s%s.csv' %
                                       (urllib.parse.quote(invoice.inventory.date.strftime("%Y%m%d")),
                                        "diff" if request.GET.get("difference") is not None else ""))
    return response

@staff_member_required
def admin_invoice_detailed(request, invoice_date=None, pk=None):
    # fetch invoice data
    if pk is None:
        invoice = OutgoingInvoice.objects_all.filter(inventory__date=parse_date(invoice_date)).last()
    else:
        invoice = OutgoingInvoice.objects_all.get(inventory__date=parse_date(invoice_date), pk=pk)
    invoice_chain = list(list(reversed(list(invoice.corrected_by_iterator()))) + [invoice] + list(invoice.correction_of_iterator()))

    latest_in_chain = invoice_chain[0]
    # TODO: what what if total is equal by chance...
    show_latest = (latest_in_chain.correction_of_id is None or
                   latest_in_chain.correction_of.total != latest_in_chain.total)
    if not show_latest:
        invoice_chain = invoice_chain[1:]
    if pk is None:
        invoice = invoice_chain[0]

    if request.method == "POST":
        if not invoice.is_temporary:
            return HttpResponse("Not invoice not fozen.")
        invoice.is_frozen = True
        invoice.save()
        invoice.inventory.may_have_changed = True
        invoice.inventory.save()
        return HttpResponseRedirect(request.path)

    if invoice.correction_of_id is None:
        invoice_table, product_ids, product_names, product_loss, product_price = get_invoice_data(invoice)
        product_price = ((i / 100., None) for i in product_price)
        product_loss = ((loss, get_loss_color(loss), None, None) for loss in product_loss)
    else:
        invoice_table_diff, product_ids_diff, product_names_diff, product_loss, product_price = \
            subtract_invoices(invoice.correction_of, invoice)
        # for now only display total amounts (override differences)
        invoice_table, product_ids, product_names, _, _ = get_invoice_data(invoice)
        product_loss = [product_loss[product_ids_diff.index(id_)] for id_ in product_ids]
        product_price = [product_price[product_ids_diff.index(id_)] for id_ in product_ids]

        product_price = ((None if i is None else i / 100., None if i2 is None else i2 / 100.) for i, i2 in product_price)
        product_loss = ((loss, get_loss_color(loss), loss2, get_loss_color(loss2)) for loss, loss2 in product_loss)

    # fetch current and nearby invoice
    current_date = parse_date(invoice_date)
    all_invoice_dates = list(get_inventory_dates())
    all_invoice_dates = all_invoice_dates[
                            max(0, all_invoice_dates.index(current_date) - 1):
                            all_invoice_dates.index(current_date) + 2]
    return render(request, 'admin/invoice.html', add_default_view_data(request, {
        "invoice_chain": invoice_chain,
        "invoice": invoice,
        "invoices": all_invoice_dates,
        "users": [i[1:] for i in invoice_table],
        "names": product_names,
        "price_each": product_price,
        "losses": product_loss,
        "date": current_date,
        "total": (sum(i) for i in list(zip(*invoice_table))[2:])
    }, "Admin - Invoice %s" % invoice.inventory.date.strftime("%d.%m.%Y"),
    pre_breadcrumbs=[(TEMPLATE_BASE_URL + "invoices/", "Invoices")]))


@login_required
def schwund_charts(request):
    if OutgoingInvoice.objects.count() != 0:
        dates, profits = zip(*OutgoingInvoice.objects.all().order_by("inventory__date").values_list("inventory__date", "profit"))
    else:
        dates, profits = [], []
    pnn = Product.objects.values_list("pk", "name")
    products, pnames = zip(*pnn)
    id_to_pname = dict(pnn)
    losses = dict([(product, [0] * len(dates)) for product in products])
    for dt, product, loss in (OutgoingInvoiceProductPosition.objects.filter((Q(invoice__corrected_by=None) | Q(invoice__corrected_by__is_frozen=False)) & Q(invoice__is_frozen=True))
                              .values_list("invoice__inventory__date", "product", "loss")):
        losses[product][dates.index(dt)] = abs(loss) if abs(loss) != float("+inf") else 100
    new_losses = []
    for k in losses:
        new_losses.append((id_to_pname[k], json.dumps(losses[k])))
    return render(request, "charts.html", add_default_view_data(request, {
        "labels_json": json.dumps([str(i) for i in dates]),
        "losses_json": new_losses,
        "gewinn_json": json.dumps([i / 100 for i in profits])
    }, "Schwund u. Gewinn"))


@login_required
def user_consumptions(request):
    # TODO: more efficient
    user = request.user
    inventories = Inventory.objects.all().order_by("date")
    inventories = inventories.exclude(pk=inventories.first().pk)
    dates_new = inventories.values_list("date", flat=True)
    table = ProductInPeriod.get_listed_consumptions_table(inventories, Product.objects.all(),
                                                          Consumption.objects.filter(user=user))
    consumptions_new = []
    for p_id, product_name in enumerate(Product.objects.all().values_list("name", flat=True)):
        product_consumptions = []
        for i_id in range(inventories.count()):
            product_consumptions.append(table[i_id][p_id])
        consumptions_new.append((product_name, product_consumptions))

    return render(request, "consumptions.html", add_default_view_data(request, {
        "dates": dates_new,
        "labels_json": [str(d) for d in dates_new],
        "consumptions": consumptions_new,
        "products": Product.objects.all(),
        "detailed_cons": Consumption.objects.filter(user=user).order_by("-date")
    }, "Consumptions, %s" % request.user.username))


def login(request):
    if request.method == "POST":
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            auth_login(request, user)
            response = HttpResponseRedirect(TEMPLATE_BASE_URL)
            response.set_cookie("temp_login", "true" if "temp_login" in request.POST else "false")
            return response
        else:
            return HttpResponse("wrong password.")
    else:
        return render(request, "login.html", add_default_view_data(request, {
            "users": (User.objects.filter(userextension__allow_login=True)
                      .annotate(max_cons_date=Max('consumption__date'))
                      .order_by("-max_cons_date"))
        }, "Login"))


def logout(request):
    auth_logout(request)
    return HttpResponseRedirect(TEMPLATE_BASE_URL)


@staff_member_required
def select_product(request):
    if request.method == "POST":
        users = json.loads(request.POST["json_data"])
        for user, products in users.items():
            user = User.objects.get(pk=int(user))
            for product, count in products.items():
                product = Product.objects.get(pk=int(product))
                Consumption(product=product, user=user, count=count, issued_by=request.user).save()
        if request.COOKIES.get("temp_login") == "true":
            auth_logout(request)
        response = HttpResponseRedirect(request.path)
        response.set_cookie("orderList", "{}")
        return response
    return render(request, "input.html", add_default_view_data(request, {
        "products": Product.objects.all(),
        "users": User.objects.all(),
        "range": range(64)
    }, "Select Product"))


@login_required
def user_invoices(request):
    dates_new = {}

    if OutgoingInvoice.objects.count() != 0:
        latest_inv_pk, latest_inv_date = list(zip(*list(OutgoingInvoice.objects.values_list("pk", "date"))))
    else:
        latest_inv_pk, latest_inv_date = [], []

    for position in (OutgoingInvoiceProductUserPosition.objects
                     .filter(user=request.user, productinvoice__invoice__in=latest_inv_pk)
                     .order_by("productinvoice__invoice__date").annotate(invoice_date=F("productinvoice__invoice__inventory__date"))
                     .prefetch_related("productinvoice")):
        if position.invoice_date not in dates_new:
            dates_new[position.invoice_date] = []
        dates_new[position.invoice_date].append((
            position.productinvoice.product.name, position.productinvoice.price_each / 100., position.count,
            position.count * position.productinvoice.price_each / 100., position.productinvoice.loss,
            get_loss_color(position.productinvoice.loss)
        ))

    return render(request, "user_abrechnung.html", add_default_view_data(request, {
        "dates": sorted([(k, v) for k, v in dates_new.items() if v], reverse=True)
    }, "Invoice, %s" % request.user.username))


@staff_member_required
def create_consumtions(request):
    if request.method == "POST":
        if "delete" in request.POST:
            Consumption.objects.get(pk=request.POST["id"]).delete()
            return HttpResponseRedirect(request.build_absolute_uri())
        else:
            data = {}
            for k, v in request.POST.items():
                if v == "":
                    continue
                if k.startswith("cons"):
                    dk, id = k.split("/")
                    if id not in data:
                        data[id] = {}
                    data[id][dk[5:]] = v

            for v in data.values():
                consumtion = Consumption(product=Product.objects.get(id=v["product"]),
                            user=User.objects.get(id=v["user"]),
                            count=v["count"],
                            issued_by=request.user)
                consumtion.save()
            return HttpResponseRedirect(request.build_absolute_uri())
    pz = 100
    p = int(request.GET["p"] if "p" in request.GET else 0)
    page_count = math.ceil(Consumption.objects.filter(issued_by=request.user).count() / pz)

    return render(request, "admin/admin_create_cons.html", add_default_view_data(request, {
        "range": [{"pk": -i - 1} for i in range(100)],
        "products": Product.objects.all(),
        "users": User.objects.all(),
        "pages": range(page_count),
        "current_page": p,
        "consumptions": Consumption.objects.filter(issued_by=request.user)
                         .order_by("-date", "user__username")[p*pz:(p + 1) * pz]
    }, "Admin - Consumptions"))



@staff_member_required
def admin_inventory_list(request):
    inventories = Inventory.objects.order_by("date")
    products = Product.objects.order_by("name")
    tbl_real = ProductInPeriod.get_real_consumption_list(inventories, products)
    tbl_listed = ProductInPeriod.get_listed_consumptions_table(inventories, products)
    date_n_counts_new = zip(inventories.values_list("date", flat=True),
                            numpy.sum(numpy.abs(tbl_real - tbl_listed), axis=1))
    return render(request, "admin/inventories.html", add_default_view_data(request, {
        "date_n_counts": reversed(list(date_n_counts_new))
    }, "Admin - Inventories"))


@staff_member_required
def admin_inventory(request, year=None, month=None, day=None):
    # TODO: must be more efficient
    # TODO: use default_object_post?
    if year is None:
        date_obj = None
    else:
        date_obj = date(int(year), int(month), int(day))

    data = []
    inventory = None
    if date_obj is not None:
        try:
            inventory = Inventory.objects.get(date=date_obj)
        except Inventory.DoesNotExist as e:
            return HttpResponseNotFound("Inventory not found for this date.")
    else:
        tmp_date = Inventory.objects.all().aggregate(Max("date"))["date__max"]
        tmp_date = max(date(3600, 12, 1), (tmp_date or date(3600, 12, 1))) + timedelta(days=1)
        inventory = Inventory(date=tmp_date)

    if request.method == "POST":
        if "delete" in request.POST:
            inventory.delete()
            return HttpResponseRedirect(TEMPLATE_BASE_URL + "inventories/")

        try:
            inventory.date = datetime.strptime(request.POST["date"], "%d.%m.%Y")
        except ValueError:
            inventory.date = datetime.now()
        inventory.save()
        for name, values in request.POST.items():
            if name.startswith("inv-"):
                try:
                    try:
                        prod_inv = ProductInventory.objects.get(inventory=inventory, product_id=int(name[4:]))
                        prod_inv.count = values
                    except ProductInventory.DoesNotExist:
                        prod_inv = ProductInventory(inventory=inventory, product_id=int(name[4:]), count=values)
                    prod_inv.save()
                except ValueError:
                    pass
        # inventory.save()
        return HttpResponseRedirect(urllib.parse.urljoin(TEMPLATE_BASE_URL + "inventory/", inventory.date.strftime("%Y-%m-%d")))

    for prod_type in ProductType.objects.all():
        type_data = []
        for product in prod_type.product_set.order_by("name"):
            bp = BillingPeriod(inventory)
            pip = ProductInPeriod(bp, product)
            try:
                product_inventory = product.productinventory_set.get(inventory=inventory)
            except ProductInventory.DoesNotExist as e:
                product_inventory = None
            previous = 0
            try:
                if bp.previous_billing_period is not None:
                    previous = bp.previous_billing_period.inventory.productinventory_set.get(product=product).count
            except ProductInventory.DoesNotExist as e:
                previous = 0
            expected = previous - pip.get_listed_consumptions() + pip.get_total_orders()
            type_data.append((
                product,
                product_inventory.count if product_inventory else 0,
                expected,
                pip.get_loss(),
                pip.get_listed_consumptions(),
                pip.get_real_consumption(),
                get_loss_color(pip.get_loss())
            ))
        data.append((prod_type, type_data))
    return render(request, "admin/inventory.html", add_default_view_data(request, {
        "date": date_obj,
        "data": data
    }, "Admin - Inventory: %s" % inventory.date if inventory.id else "Admin - New Inventory",
    pre_breadcrumbs=[(TEMPLATE_BASE_URL + "inventories/", "Inventories")]))


@staff_member_required
def admin_products(request):
    return render(request, "admin/products.html", add_default_view_data(request, {
        "products": Product.objects.all().order_by("name")
    }, "Admin - Products"))


@staff_member_required
def admin_product(request, id_=None):
    return default_object_post(request, Product, id_, "admin/product.html", {
        "product_types": ProductType.objects.all()
    }, [
        ("name", "name", str),
        ("product_type", "product_type_id", int)
    ], lambda obj: "Admin - Product: %s" % obj.name if obj.id else "Admin - New Product",
    parent_page="/products/",  can_delete=lambda obj: not (ProductInventory.objects.filter(product=obj)
                                                              .aggregate(Sum("count"))["count__sum"]),
    pre_breadcrumbs=[(TEMPLATE_BASE_URL + "products", "Products")])


@staff_member_required
def admin_incoming_invoices(request):
    return render(request, "admin/incoming_invoices.html", add_default_view_data(request, {
       "incoming_invoices": IncomingInvoice.objects.all().order_by("-date")
    }, "Admin - Incoming Invoices"))


@staff_member_required
def admin_incoming_invoice(request, id_=None):
    def additional_stuff(obj):
        obj.save()
        for i in set((i.split("/")[1] for i in request.POST if "/" in i)):
            count = request.POST["count/" + str(i)]
            each_cents = request.POST["each_cents/" + str(i)]
            product = request.POST["product/" + str(i)]
            if each_cents and count and int(each_cents) > 0 and int(count) > 0:
                if int(i) < 0:
                    order = Order(incoming_invoice=obj)
                else:
                    order = obj.order_set.get(pk=int(i))
                order.each_cents = each_cents
                order.product_id = product
                order.count = count
                order.save()
            elif int(i) >= 0:
                obj.order_set.get(pk=int(i)).delete()
        return True, ""
    return default_object_post(request, IncomingInvoice, id_, "admin/incoming_invoice.html", {
        "products": Product.objects.all().order_by("name"),
        "range": [{"pk": -i - 1} for i in range(10)]
    }, [
        ("invoice_id", "invoice_id", str),
        ("date", "date", lambda s: datetime.strptime(s, "%d.%m.%Y"))
    ], lambda obj: "Admin - Incoming Invoice: %s" % obj.invoice_id if obj.id else "Admin - New Incoming Invoice",
        additional_stuff, parent_page="/incoming_invoices",
    pre_breadcrumbs=[(TEMPLATE_BASE_URL + "incoming_invoices/", "Incoming Invoices")])


def default_object_post(request, Model, id, template_name, additional_view_data,
                        fields, heading, object_validator=None, parent_page="/",
                        can_delete=None, pre_breadcrumbs=None):
    """
    :param request:
    :param Model:
    :param id:
    :param template_name:
    :param additional_view_data:
    :param fields: list of (post_name, field_name, formatter)
    :param object_validator
    :param parent_page
    :param can_delete
    :return:
    """
    assert issubclass(Model, models.Model)
    # get object
    if id is None:
        obj = Model()
    else:
        try:
            obj = Model.objects.get(pk=id)
        except Model.DoesNotExist:
            return HttpResponseNotFound("Does not exist.")

    # prepare view data
    view_data = additional_view_data.copy()
    view_data.update({
        "obj": obj
    })
    http_status = 200
    # update object if POST
    if request.method == "POST":
        def _save():
            for post_name, field_name, formatter in (fields or []):
                if post_name not in request.POST:
                    return 400
                try:
                    setattr(obj, field_name, formatter(request.POST[post_name]))
                except ValueError:
                    # value was invalid.
                    # TODO: best way to check for this condition?
                    return 400

            if object_validator:
                valid, view_data["error"] = object_validator(obj)
                if not valid:
                    return 400

            try:
                obj.save()
            except IntegrityError:
                return 400
            return 200

        if "delete" in request.POST:
            if obj.id is not None and (can_delete is None or can_delete(obj)):
                obj.delete()
            else:
                return HttpResponseBadRequest("Cannot delete that.")
            return HttpResponseRedirect(parent_page)

        http_status = _save()

        if http_status == 200:
            view_data["success"] = "Object Saved."
        else:
            view_data["error"] = "Something went wrong."
        if id is None:
            return HttpResponseRedirect(urllib.parse.urljoin(request.path, str(obj.pk)))
        return HttpResponseRedirect(request.path)

    # generate response
    return render(request, template_name,
                  add_default_view_data(request, view_data, heading(obj), pre_breadcrumbs=pre_breadcrumbs),
                  status=http_status)
