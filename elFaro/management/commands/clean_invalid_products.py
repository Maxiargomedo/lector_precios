from django.core.management.base import BaseCommand
from elFaro.models import Producto
from decimal import Decimal, InvalidOperation

class Command(BaseCommand):
    help = 'Elimina productos con valores decimales inválidos en precio o precio_vecino.'

    def handle(self, *args, **options):
        productos = Producto.objects.all()
        count = 0
        for producto in productos:
            try:
                # Intentar convertir los valores a Decimal
                Decimal(str(producto.precio))
                if producto.precio_vecino is not None:
                    Decimal(str(producto.precio_vecino))
            except (InvalidOperation, ValueError):
                self.stdout.write(self.style.WARNING(f'Eliminando producto ID {producto.id} con valores corruptos.'))
                producto.delete()
                count += 1
        self.stdout.write(self.style.SUCCESS(f'Productos eliminados: {count}'))
