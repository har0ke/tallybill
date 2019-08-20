import numpy
from datetime import date
from django.contrib.auth.models import User

from main.models import OutgoingInvoice, OutgoingInvoiceProductUserPosition
from tallybill.tally_settings import LOSS_WARN_LEVEL, LOSS_ERROR_LEVEL, TEMPLATE_BASE_URL


def add_default_view_data(request, data_dict, title, pre_breadcrumbs=None):
    data_dict.update({
        "logged_in": request.user,
        "base_url": TEMPLATE_BASE_URL,
        "title": title,
        "breadcrumbs": (pre_breadcrumbs if pre_breadcrumbs else []) + [("#", title)]
    })
    return data_dict


def get_inventory_dates():
    return OutgoingInvoice.objects_all.values_list("inventory__date", flat=True).distinct().order_by("inventory__date")


def parse_date(date_str):
    # date_str in format YYYY-MM-DD
    return date(int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10]))


def get_loss_color(loss):
    return ("red" if abs(loss) > LOSS_ERROR_LEVEL * 100 else
            ("orange" if abs(loss) > LOSS_WARN_LEVEL * 100 else "green"))


def merge_sorted(a, b, missing, inserted, kept):
    def _next(iterator):
        try:
            return next(iterator)
        except StopIteration:
            return None

    iter1 = iter(a)
    iter2 = iter(b)
    e1 = _next(iter1)
    e2 = _next(iter2)
    while e1 is not None and e2 is not None:
        if e1 < e2:
            yield missing(e1)  # e1 missing?
            e1 = _next(iter1)
        if e1 > e2:
            yield inserted(e2)  # e2 inserted?
            e2 = _next(iter2)
        if e1 == e2:
            yield kept(e1, e2)
            e1 = _next(iter1)
            e2 = _next(iter2)
    while e1:
        yield e1
        e1 = _next(iter1)
    while e2:
        yield e2
        e2 = _next(iter2)


def get_invoice_data(invoice):
    # get all product information for invoice
    invoice_products = invoice.outgoinginvoiceproductposition_set.order_by("product__name")
    product_ids, product_names, product_loss, product_price = (
        zip(*invoice_products.values_list("product__id", "product__name", "loss", "price_each")))
    id_to_username = dict(User.objects.all().values_list("pk", "username"))

    # get user data
    invoice_table = []
    last_user = [-1]
    user_query = (OutgoingInvoiceProductUserPosition.objects.filter(productinvoice__invoice=invoice)
                  .values_list("user_id", "productinvoice__product__id", "count", "productinvoice__price_each")
                  .order_by("user__username"))

    for user_id, product_id, count, price in user_query:
        if user_id != last_user[0]:
            last_user = [user_id, id_to_username[user_id]] + [0] * (len(product_ids) + 1)
            invoice_table.append(last_user)
        last_user[product_ids.index(product_id) + 3] = count * price / 100.

    for user in invoice_table:
        user[2] = sum(user[3:])

    return invoice_table, product_ids, product_names, product_loss, product_price


def subtract_invoices(invoice1, invoice2):
    invoice_table1, product_ids1, product_names1, product_loss1, product_price1 = get_invoice_data(invoice1)
    invoice_table2, product_ids2, product_names2, product_loss2, product_price2 = get_invoice_data(invoice2)

    product_indices = list(merge_sorted(sorted(product_ids1), sorted(product_ids2),
                                        inserted=lambda e: (None, product_ids2.index(e)),
                                        missing=lambda e: (product_ids1.index(e), None),
                                        kept=lambda e, e2: (product_ids1.index(e), product_ids2.index(e2))))
    users1 = [u[0] for u in invoice_table1]
    users2 = [u[0] for u in invoice_table2]
    user_indices = list(merge_sorted(sorted(users1), sorted(users2),
                                     inserted=lambda e: (None, users2.index(e)),
                                     missing=lambda e: (users1.index(e), None),
                                     kept=lambda e, e2: (users1.index(e), users2.index(e2))))
    new_invoice_table = [[0] * (len(product_indices) + 3) for _ in range(len(user_indices))]
    for uid, (ui1, ui2) in enumerate(user_indices):
        if ui2 is not None:
            new_invoice_table[uid][0] = invoice_table2[ui2][0]
            new_invoice_table[uid][1] = invoice_table2[ui2][1]
        elif ui1 is not None:
            new_invoice_table[uid][0] = invoice_table1[ui1][0]
            new_invoice_table[uid][1] = invoice_table1[ui1][1]
        else:
            raise Exception("shoudnt be happening")
        for pid, (pi1, pi2) in enumerate(product_indices):
            if ui2 is not None and pi2 is not None:
                if ui1 is not None and pi1 is not None:
                    new_invoice_table[uid][pid + 3] = invoice_table2[ui2][pi2 + 3] - invoice_table1[ui1][pi1 + 3]
                else:
                    new_invoice_table[uid][pid + 3] = invoice_table2[ui2][pi2 + 3]
            else:
                if ui1 is not None or pi1 is not None:
                    new_invoice_table[uid][pid + 3] = invoice_table1[ui1][pi1 + 3]
                else:
                    raise Exception("shoudnt be happening")
        new_invoice_table[uid][2] = sum(new_invoice_table[uid][3:])
    new_product_names = [(product_names1[i] if i is not None else product_names2[j]) for i, j in product_indices]
    new_product_ids = [(product_ids1[i] if i is not None else product_ids2[j]) for i, j in product_indices]
    new_product_price = [(product_price1[i] if i is not None else None,
                          product_price2[j] if j is not None else None) for i, j in product_indices]
    new_product_loss = [(product_loss1[i] if i is not None else None,
                         product_loss2[j] if j is not None else None) for i, j in product_indices]

    switch_ids = numpy.argsort(new_product_names)
    new_invoice_table = [i[:3] + list(numpy.array(i[3:])[switch_ids]) for i in new_invoice_table]
    new_invoice_table = sorted(new_invoice_table, key=lambda a: a[1])

    return new_invoice_table, new_product_ids, new_product_names, new_product_loss, new_product_price
