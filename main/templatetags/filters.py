from django import template

register = template.Library()

@register.filter
def asrepr(value):
    return str(value)

@register.filter
def cents_to_euro(cents):
    return "%.2f" % (cents / 100.)

@register.filter
def datetime_to_str(date_time):
    return date_time.strftime("%d.%m.%Y %H:%M")

@register.filter
def date_to_str(date_time):
    return date_time.strftime("%d.%m.%Y")
