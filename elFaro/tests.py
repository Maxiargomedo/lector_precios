from django.test import TestCase, Client
from django.urls import reverse
from decimal import Decimal
from .models import Producto, validate_price_value
from django.core.exceptions import ValidationError


class ValidatePriceValueTest(TestCase):
    def test_precio_valido(self):
        """Precio válido no lanza excepción"""
        validate_price_value(1000)

    def test_precio_cero(self):
        """Precio cero es válido"""
        validate_price_value(0)

    def test_precio_negativo(self):
        """Precio negativo lanza ValidationError"""
        with self.assertRaises(ValidationError):
            validate_price_value(-1)

    def test_precio_muy_grande(self):
        """Precio mayor a 9999999 lanza ValidationError"""
        with self.assertRaises(ValidationError):
            validate_price_value(10000000)

    def test_precio_none(self):
        """Precio None no lanza excepción"""
        validate_price_value(None)


class ProductoModelTest(TestCase):
    def test_crear_producto(self):
        """Se puede crear un producto con datos válidos"""
        producto = Producto(
            nombre="Arroz Grado 1",
            codigo_barras="7802800000001",
            precio=Decimal("1500"),
        )
        producto.save()
        self.assertEqual(Producto.objects.count(), 1)

    def test_str_producto(self):
        """El método __str__ devuelve nombre y código de barras"""
        producto = Producto(
            nombre="Leche Soprole",
            codigo_barras="7802800000002",
            precio=Decimal("900"),
        )
        producto.save()
        self.assertIn("Leche Soprole", str(producto))
        self.assertIn("7802800000002", str(producto))

    def test_codigo_barras_unico(self):
        """No se pueden crear dos productos con el mismo código de barras"""
        Producto.objects.create(
            nombre="Producto A",
            codigo_barras="1234567890123",
            precio=Decimal("100"),
        )
        with self.assertRaises(ValidationError):
            Producto.objects.create(
                nombre="Producto B",
                codigo_barras="1234567890123",
                precio=Decimal("200"),
            )


class HomeViewTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_home_carga_correctamente(self):
        """La página principal carga con código 200"""
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)

    def test_ping_responde(self):
        """El endpoint /ping/ responde con 'pong'"""
        response = self.client.get("/ping/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "pong")

    def test_lista_productos_carga(self):
        """La vista de lista de productos carga correctamente"""
        response = self.client.get(reverse("lista_productos"))
        self.assertEqual(response.status_code, 200)
