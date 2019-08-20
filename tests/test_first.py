import datetime
import inspect
from time import sleep
from urllib import parse

from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.servers.basehttp import WSGIServer
from django.test.testcases import LiveServerThread, QuietWSGIRequestHandler
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait

from main.billing import BillingPeriod, RecalculateThread
from main.models import Product, ProductType, IncomingInvoice, Order, Consumption, Inventory, ProductInventory, \
    OutgoingInvoice, OutgoingInvoiceProductUserPosition, OutgoingInvoiceProductPosition, UserExtension


class TestCaseData1(object):

    def __init__(self):
        self.admin = User.objects.create(username="admin", is_staff=True)
        self.admin.set_password("1234")
        self.admin.save()

        self.user1 = User.objects.create(username="User1", email="bla@bla.bla")
        self.user1.set_password("1234")
        self.user1.save()
        self.user2 = User.objects.create(username="User2", email="bla@bla.bla")
        self.user3 = User.objects.create(username="User3", email="bla@bla.bla")

        self.product_type_drinks = ProductType.objects.create(name="Drinks")
        self.product_water = Product.objects.create(name="Water", product_type=self.product_type_drinks)
        self.product_soda = Product.objects.create(name="Soda", product_type=self.product_type_drinks)
        self.product_beer = Product.objects.create(name="Beer", product_type=self.product_type_drinks)

        incoming_invoice_date = datetime.date(2019, 1, 1)
        self.incoming_invoice = IncomingInvoice.objects.create(
            invoice_id="inv-001",
            date=incoming_invoice_date)

        self.incoming_invoice_position1 = Order.objects.create(
            incoming_invoice=self.incoming_invoice,
            product=self.product_soda,
            each_cents=20,
            count=20)

        self.incoming_invoice_position2 = Order.objects.create(
            incoming_invoice=self.incoming_invoice,
            product=self.product_beer,
            each_cents=80,
            count=24)

        self.consumption1 = Consumption.objects.create(product=self.product_beer, user=self.user1, count=4, date=datetime.datetime(2019, 1, 4), issued_by=self.admin)
        self.consumption2 = Consumption.objects.create(product=self.product_soda, user=self.user1, count=6, date=datetime.datetime(2019, 1, 2), issued_by=self.admin)
        self.consumption3 = Consumption.objects.create(product=self.product_beer, user=self.user2, count=4, date=datetime.datetime(2019, 1, 4), issued_by=self.admin)
        self.consumption4 = Consumption.objects.create(product=self.product_beer, user=self.user3, count=3, date=datetime.datetime(2019, 1, 4), issued_by=self.admin)

        self.inventory1 = Inventory.objects.create(date=datetime.datetime(2019, 1, 20))
        self.inventory1_beer = ProductInventory.objects.create(product=self.product_beer, count=24 - 11, inventory=self.inventory1)
        self.inventory1_soda = ProductInventory.objects.create(product=self.product_soda, count=20 - 7, inventory=self.inventory1)

        period = BillingPeriod(self.inventory1)
        period.recalculate_temporary_invoices()
        invoice = period.invoices.first()
        invoice.is_frozen = True
        invoice.save()
        invoice.inventory.may_have_changed = True
        invoice.inventory.save()


class LiveServerSingleThread(LiveServerThread):
    """Runs a single threaded server rather than multi threaded. Reverts https://github.com/django/django/pull/7832"""

    def _create_server(self):
        return WSGIServer((self.host, self.port), QuietWSGIRequestHandler, allow_reuse_address=False)

def replace_input_value(web_element, value):
    web_element.send_keys(Keys.CONTROL + "a")
    web_element.send_keys(value)


class CoverageTest(StaticLiveServerTestCase):

    # server_thread_class = LiveServerSingleThread

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.selenium = WebDriver()
        cls.selenium.implicitly_wait(2)

    @classmethod
    def tearDownClass(cls):
        cls.selenium.quit()
        super().tearDownClass()

    def setUp(self):
        self.recalculate_thread = RecalculateThread()
        self.recalculate_thread.start()

        self.scenario_data = TestCaseData1()

        self.selenium.get('%s%s' % (self.live_server_url, '/admin/login/?next=/'))
        username_input = self.selenium.find_element_by_name("username")
        username_input.send_keys('admin')
        password_input = self.selenium.find_element_by_name("password")
        password_input.send_keys('1234')
        self.selenium.find_element_by_xpath('//input[@value="Log in"]').click()
        self.wait_for_page()

        self.assertEqual(parse.urlparse(self.selenium.current_url).path, "/")

    def tearDown(self):
        self.recalculate_thread.running = False
        self.recalculate_thread.join()
        self.selenium.get('%s%s' % (self.live_server_url, '/logout/'))
        self.assertEqual(parse.urlparse(self.selenium.current_url).path, "/admin/login/")

    def get_simple_list_text(self):
        return set(element.text
                   for element
                   in self.selenium.find_elements_by_xpath(
                        '//a[@class="list-group-item list-group-item-action"]'))

    def wait_for_page(self):
        return self.selenium.find_elements_by_class_name("navbar-header")

    def test_users(self):
        self.selenium.get('%s%s' % (self.live_server_url, '/users/'))
        self.assertEqual(len(self.get_simple_list_text()), 4)

        self.selenium.find_element_by_xpath('//span[@class="glyphicon glyphicon-plus"]/parent::a').click()
        username, mail = "NewUser", "default@default.default"

        self.selenium.find_element_by_name("username").send_keys(username)
        self.selenium.find_element_by_name("email").send_keys(mail)
        self.selenium.find_element_by_xpath('//button[text()="Save"]').click()
        self.wait_for_page()
        created_url = self.selenium.current_url

        self.assertTrue(User.objects.filter(username=username, email=mail).exists())

        self.selenium.get('%s%s' % (self.live_server_url, '/users/'))

        users = self.get_simple_list_text()
        self.assertIn("NewUser", users)
        self.assertIn("admin", users)
        self.assertIn("User1", users)
        self.assertIn("User2", users)
        self.assertIn("User3", users)
        self.assertEqual(len(users), 5)

        self.selenium.get(created_url)
        self.selenium.find_element_by_name("email").send_keys("2")
        self.selenium.find_element_by_xpath('//button[text()="Save"]').click()
        self.wait_for_page()
        self.assertTrue(User.objects.filter(username=username, email="2" + mail).exists())

        self.selenium.get(created_url)
        self.selenium.find_element_by_xpath('//button[@data-toggle="modal" and @data-target="#confirm-delete"]').click()
        self.selenium.find_element_by_xpath('//button[@type="submit" and @form="delete_form"]').click()
        self.wait_for_page()
        self.assertTrue(User.objects.filter(username=username, email="2" + mail).exists())

    def test_products(self):
        self.selenium.get('%s%s' % (self.live_server_url, '/products/'))
        self.assertEqual(len(self.get_simple_list_text()), 3)

        self.selenium.find_element_by_xpath('//span[@class="glyphicon glyphicon-plus"]/parent::a').click()
        self.selenium.find_element_by_name("name").send_keys("Juice")
        self.selenium.find_element_by_xpath('//button[text()="Save"]').click()
        self.wait_for_page()
        created_url = self.selenium.current_url

        self.assertTrue(Product.objects.filter(name="Juice").exists())

        self.selenium.get('%s%s' % (self.live_server_url, '/products/'))
        products = self.get_simple_list_text()

        self.assertIn("Water", products)
        self.assertIn("Soda", products)
        self.assertIn("Beer", products)
        self.assertIn("Juice", products)
        self.assertEqual(len(products), 4)

        self.selenium.get(created_url)
        self.selenium.find_element_by_xpath('//button[@data-toggle="modal" and @data-target="#confirm-delete"]').click()
        self.selenium.find_element_by_xpath('//button[@type="submit" and @form="delete_form"]').click()
        self.wait_for_page()
        self.assertFalse(Product.objects.filter(name="Juice").exists())

    def test_incoming_invoices(self):
        self.selenium.get('%s%s' % (self.live_server_url, '/incoming_invoices/'))
        self.assertEqual(len(self.get_simple_list_text()), 1)

        self.selenium.find_element_by_xpath('//span[@class="glyphicon glyphicon-plus"]/parent::a').click()
        self.selenium.find_element_by_name("invoice_id").send_keys("inv-002")
        self.selenium.find_element_by_name("date").send_keys(Keys.CONTROL + "a")
        self.selenium.find_element_by_name("date").send_keys("02.01.2019")

        self.selenium.find_element_by_xpath("//select[@name='product/-1']/option[text()='Water']").click()
        self.selenium.find_element_by_xpath("//input[@name='count/-1']").send_keys(Keys.CONTROL + "a")
        self.selenium.find_element_by_xpath("//input[@name='count/-1']").send_keys("10")
        self.selenium.find_element_by_xpath("//input[@name='each_cents/-1']").send_keys(Keys.CONTROL + "a")
        self.selenium.find_element_by_xpath("//input[@name='each_cents/-1']").send_keys("30")

        self.selenium.find_element_by_xpath("//select[@name='product/-2']/option[text()='Soda']").click()
        self.selenium.find_element_by_xpath("//input[@name='count/-2']").send_keys(Keys.CONTROL + "a")
        self.selenium.find_element_by_xpath("//input[@name='count/-2']").send_keys("20")
        self.selenium.find_element_by_xpath("//input[@name='each_cents/-2']").send_keys(Keys.CONTROL + "a")
        self.selenium.find_element_by_xpath("//input[@name='each_cents/-2']").send_keys("50")
        self.selenium.find_element_by_xpath('//button[text()="Save"]').click()
        self.wait_for_page()

        created_url = self.selenium.current_url

        inv = IncomingInvoice.objects.get(invoice_id="inv-002", date=datetime.datetime(2019, 1, 2))
        orders = [(order.product.name, order.count, order.each_cents) for order in inv.order_set.all()]
        self.assertEqual(len(orders), 2)
        self.assertIn(("Soda", 20, 50), orders)
        self.assertIn(("Water", 10, 30), orders)

        self.selenium.get('%s%s' % (self.live_server_url, '/incoming_invoices/'))
        invoices = [i.split("\n")[0] for i in self.get_simple_list_text()]

        self.assertIn("inv-001", invoices)
        self.assertIn("inv-002", invoices)
        self.assertEqual(len(invoices), 2)

        self.selenium.get(created_url)
        order_id = inv.order_set.first().id
        self.selenium.find_element_by_xpath("//select[@name='product/%d']/option[text()='Beer']" % order_id).click()
        self.selenium.find_element_by_xpath("//input[@name='count/%d']" % order_id).send_keys(Keys.CONTROL + "a")
        self.selenium.find_element_by_xpath("//input[@name='count/%d']" % order_id).send_keys("5")
        self.selenium.find_element_by_xpath("//input[@name='each_cents/%d']" % order_id).send_keys(Keys.CONTROL + "a")
        self.selenium.find_element_by_xpath("//input[@name='each_cents/%d']" % order_id).send_keys("5")
        order_id = inv.order_set.last().id
        self.selenium.find_element_by_xpath("//input[@name='count/%d']" % order_id).send_keys(Keys.CONTROL + "a")
        self.selenium.find_element_by_xpath("//input[@name='count/%d']" % order_id).send_keys(Keys.DELETE)
        self.selenium.find_element_by_xpath("//input[@name='each_cents/%d']" % order_id).send_keys(Keys.CONTROL + "a")
        self.selenium.find_element_by_xpath("//input[@name='each_cents/%d']" % order_id).send_keys(Keys.DELETE)

        self.selenium.find_element_by_xpath('//button[text()="Save"]').send_keys(Keys.NULL)
        #sleep()
        self.selenium.find_element_by_xpath('//button[text()="Save"]').click()
        self.wait_for_page()

        inv = IncomingInvoice.objects.get(invoice_id="inv-002", date=datetime.datetime(2019, 1, 2))
        orders = [(order.product.name, order.count, order.each_cents) for order in inv.order_set.all()]

        self.assertEqual(len(orders), 1)
        self.assertIn(("Beer", 5, 5), orders)

        self.selenium.get(created_url)
        self.selenium.find_element_by_xpath('//button[@data-toggle="modal" and @data-target="#confirm-delete"]').click()
        self.selenium.find_element_by_xpath('//button[@type="submit" and @form="delete_form"]').click()
        self.wait_for_page()
        self.assertFalse(IncomingInvoice.objects.filter(invoice_id="inv-002", date=datetime.datetime(2019, 1, 2)).exists())

    def test_admin_consumption(self):
        self.selenium.get('%s%s' % (self.live_server_url, '/create_consumtions/'))
        consumption_elements = self.selenium\
            .find_element_by_class_name("table-striped")\
            .find_element_by_tag_name("tbody")\
            .find_elements_by_tag_name("tr")
        self.assertEqual(len(consumption_elements), 4)

        replace_input_value(self.selenium.find_element_by_xpath("//input[@id='cons-product/-1']"), "Soda")
        replace_input_value(self.selenium.find_element_by_xpath("//input[@name='cons-count/-1']"), "5")
        replace_input_value(self.selenium.find_element_by_xpath("//input[@id='cons-user/-1']"), "User1")

        self.selenium.find_element_by_xpath("//button[text()='Save']").click()

        consumption_elements = self.selenium\
            .find_element_by_class_name("table-striped")\
            .find_element_by_tag_name("tbody")\
            .find_elements_by_tag_name("tr")
        self.assertEqual(len(consumption_elements), 5)

        self.selenium.find_elements_by_xpath("//button[contains(@class, 'glyphicon-remove')]")[0].click()
        self.selenium.find_element_by_xpath("//button[text()='Delete']").click()

        consumption_elements = self.selenium\
            .find_element_by_class_name("table-striped")\
            .find_element_by_tag_name("tbody")\
            .find_elements_by_tag_name("tr")
        self.assertEqual(len(consumption_elements), 4)

    def test_charts(self):
        self.selenium.get('%s%s' % (self.live_server_url, '/consumptions/'))
        self.wait_for_page()

        self.selenium.get('%s%s' % (self.live_server_url, '/'))
        self.selenium.find_element_by_class_name("product-button").find_element_by_class_name("product-button-one").click()
        self.selenium.find_element_by_xpath('//button[text()="OK"]').click()
        self.wait_for_page()

        self.selenium.get('%s%s' % (self.live_server_url, '/consumptions/'))
        consumption_elements = self.selenium\
            .find_element_by_class_name("table-striped")\
            .find_element_by_tag_name("tbody")\
            .find_elements_by_tag_name("tr")
        self.assertEqual(len(consumption_elements), 1)

        self.selenium.get('%s%s' % (self.live_server_url, '/charts/'))
        self.wait_for_page()

        self.selenium.get('%s%s' % (self.live_server_url, '/user_invoices/'))
        self.wait_for_page()

    def test_inventory(self):
        self.selenium.get('%s%s' % (self.live_server_url, '/inventories/'))
        self.assertEqual(len(self.get_simple_list_text()), 1)

        self.selenium.find_element_by_xpath('//span[@class="glyphicon glyphicon-plus"]/parent::a').click()

        self.selenium.find_element_by_name("date").send_keys(Keys.CONTROL + "a")
        self.selenium.find_element_by_name("date").send_keys("03.01.2019")
        for p_id, amount in [
            (Product.objects.get(name="Beer").pk, 24),
            (Product.objects.get(name="Soda").pk, 14),
            (Product.objects.get(name="Water").pk, 0)
        ]:
            self.selenium.find_element_by_name("inv-%d" % p_id).send_keys(Keys.CONTROL + "a")
            self.selenium.find_element_by_name("inv-%d" % p_id).send_keys(str(amount))

        self.selenium.find_element_by_xpath('//button[text()="Save"]').click()
        self.wait_for_page()

        sleep(1)  # time to recalculate

        self.selenium.get('%s%s' % (self.live_server_url, '/inventories/'))
        self.wait_for_page()

        self.selenium.get('%s%s' % (self.live_server_url, '/invoices/'))
        self.assertEqual(len(self.get_simple_list_text()), 2)

        self.selenium.find_elements_by_class_name("list-group-item")[0].click()
        for csv_a in self.selenium.find_elements_by_xpath('//a[@target="_blank"]'):
            self.selenium.get(csv_a.get_attribute("href"))
        self.selenium.find_element_by_xpath("//button[text()='Submit Changes']").click()
        self.selenium.find_element_by_xpath("//button[text()='Submit']").click()
        self.assertEqual(len(self.selenium.find_elements_by_xpath("//button[text()='Submit Changes']")), 0)


        self.selenium.get('%s%s' % (self.live_server_url, '/invoices/'))
        self.assertEqual(len(self.get_simple_list_text()), 2)
        self.selenium.find_elements_by_class_name("list-group-item")[1].click()
        self.wait_for_page()

    def test_login(self):

        self.selenium.get('%s%s' % (self.live_server_url, '/logout/'))
        self.wait_for_page()
        self.assertEqual(parse.urlparse(self.selenium.current_url).path, "/admin/login/")

        self.selenium.get('%s%s' % (self.live_server_url, '/accounts/login/?next=/'))
        self.selenium.find_element_by_xpath('//button[text()="User1"]').click()
        password_input = self.selenium.find_element_by_name("password")
        password_input.send_keys('1234')
        self.selenium.find_element_by_xpath('//button[text()="Add"]').click()
        self.assertEqual(parse.urlparse(self.selenium.current_url).path, "/admin/login/")

        self.selenium.get('%s%s' % (self.live_server_url, '/user_invoices/'))
        self.wait_for_page()

        self.selenium.get('%s%s' % (self.live_server_url, '/consumptions/'))
        consumption_elements = self.selenium\
            .find_element_by_class_name("table-striped")\
            .find_element_by_tag_name("tbody")\
            .find_elements_by_tag_name("tr")
        self.assertEqual(len(consumption_elements), 2)

    def test_trivial(self):

        for O in [OutgoingInvoice, OutgoingInvoiceProductUserPosition, OutgoingInvoiceProductPosition, Consumption,
                  Order, ProductType, Product, UserExtension]:
            str(O.objects.first()), repr(O.objects.first())



