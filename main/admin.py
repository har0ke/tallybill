from django.contrib import admin

# Register your models here.
from main.models import Inventory, Product, ProductType

admin.site.register(Inventory)
admin.site.register(Product)
admin.site.register(ProductType)