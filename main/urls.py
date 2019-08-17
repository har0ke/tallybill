from datetime import datetime
from django.conf.urls import url

from . import views


def time_measure(view):
    def _wrapper(*args, **kwargs):
        b = datetime.now()
        ret = view(*args, **kwargs)
        print("View '%s' took %.2fms" % (view.__name__, (datetime.now() - b).total_seconds() * 1000.))
        return ret

    return _wrapper


urlpatterns = [
    # everyone
    url(r'^accounts/login/$', time_measure(views.login)),
    url(r'^logout/$', time_measure(views.logout)),

    # user - consumptions
    url(r'^$', time_measure(views.select_product)),
    url(r'^consumptions/$', time_measure(views.user_consumptions)),

    # user - abrechnung
    url(r'^user_invoices/$', time_measure(views.user_invoices)),

    # user - charts
    url(r'^charts/$', time_measure(views.schwund_charts)),

    # admin - invoices
    url(r'^invoices/$', time_measure(views.admin_invoices_list)),
    url(r'^invoice_csv/(?P<pk>[0-9]+)/$', time_measure(views.download_csv)),
    url(r'^invoice/(?P<invoice_date>[0-9]{4}-[0-9]{2}-[0-9]{2})/$', time_measure(views.admin_invoice_detailed)),
    url(r'^invoice/(?P<invoice_date>[0-9]{4}-[0-9]{2}-[0-9]{2})/(?P<pk>[0-9]+)/$', time_measure(views.admin_invoice_detailed)),

    # admin - inventory
    # TODO: a lot
    url(r'^user/(?P<id_>\d+)/$', time_measure(views.admin_user_edit)),
    url(r'^user/$', time_measure(views.admin_user_edit)),

    url(r'^users/$', time_measure(views.admin_users)),
    url(r'^products/$', time_measure(views.admin_products)),
    url(r'^product/(?P<id_>\d+)/$', time_measure(views.admin_product)),
    url(r'^product/$', time_measure(views.admin_product)),
    url(r'^incoming_invoices/$', time_measure(views.admin_incoming_invoices)),
    url(r'^incoming_invoice/(?P<id_>\d+)/$', time_measure(views.admin_incoming_invoice)),
    url(r'^incoming_invoice/$', time_measure(views.admin_incoming_invoice)),

    # admin verbrauch
    url(r'^create_consumtions/$', time_measure(views.create_consumtions)),

    url(r'^inventories/$', time_measure(views.admin_inventory_list)),
    url(r'^inventory/(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})/$', time_measure(views.admin_inventory)),
    url(r'^inventory/$', time_measure(views.admin_inventory))
]