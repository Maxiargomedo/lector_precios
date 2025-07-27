from django.core.management.base import BaseCommand
from elFaro.views import enviar_notificacion_producto_no_encontrado

class Command(BaseCommand):
    help = 'Prueba el envío de notificación de producto no encontrado'

    def add_arguments(self, parser):
        parser.add_argument('codigo_barras', type=str, help='Código de barras del producto a probar')
        
    def handle(self, *args, **options):
        codigo_barras = options['codigo_barras']
        
        self.stdout.write(f"=== PROBANDO NOTIFICACIÓN DE PRODUCTO NO ENCONTRADO ===")
        self.stdout.write(f"Código de barras: {codigo_barras}")
        self.stdout.write(f"Destinatario: elfarodealgarrobo2@gmail.com")
        self.stdout.write("")
        
        try:
            resultado = enviar_notificacion_producto_no_encontrado(codigo_barras, '192.168.1.200')
            
            if resultado:
                self.stdout.write(self.style.SUCCESS('✅ Notificación enviada exitosamente'))
            else:
                self.stdout.write(self.style.ERROR('❌ Error enviando notificación'))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'💥 Error: {str(e)}'))
            import traceback
            self.stdout.write(self.style.ERROR(f'Traceback: {traceback.format_exc()}'))
