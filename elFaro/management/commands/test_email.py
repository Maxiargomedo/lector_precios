from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings

class Command(BaseCommand):
    help = 'Prueba el envío de correos electrónicos'

    def handle(self, *args, **options):
        try:
            # Verificar configuración
            self.stdout.write("=== CONFIGURACIÓN DE CORREO ===")
            self.stdout.write(f"EMAIL_BACKEND: {settings.EMAIL_BACKEND}")
            self.stdout.write(f"EMAIL_HOST: {settings.EMAIL_HOST}")
            self.stdout.write(f"EMAIL_PORT: {settings.EMAIL_PORT}")
            self.stdout.write(f"EMAIL_USE_TLS: {settings.EMAIL_USE_TLS}")
            self.stdout.write(f"EMAIL_HOST_USER: {settings.EMAIL_HOST_USER}")
            self.stdout.write(f"ADMIN_EMAIL: {settings.ADMIN_EMAIL}")
            self.stdout.write(f"NOTIFICATION_FROM_EMAIL: {settings.NOTIFICATION_FROM_EMAIL}")
            
            # Enviar correo de prueba
            self.stdout.write("\n=== ENVIANDO CORREO DE PRUEBA ===")
            
            resultado = send_mail(
                subject='🧪 Prueba de correo - El Faro',
                message='Este es un correo de prueba para verificar que el sistema de notificaciones funciona correctamente.',
                from_email=settings.NOTIFICATION_FROM_EMAIL,
                recipient_list=[settings.ADMIN_EMAIL],
                fail_silently=False
            )
            
            if resultado:
                self.stdout.write(self.style.SUCCESS('✅ Correo procesado exitosamente'))
                self.stdout.write(f"Desde: {settings.NOTIFICATION_FROM_EMAIL}")
                self.stdout.write(f"Hacia: {settings.ADMIN_EMAIL}")
                
                if 'console' in settings.EMAIL_BACKEND:
                    self.stdout.write(self.style.WARNING('📺 Usando backend de consola - el correo se muestra arriba'))
                else:
                    self.stdout.write(self.style.SUCCESS('📧 Correo enviado por SMTP'))
            else:
                self.stdout.write(self.style.ERROR('❌ Error procesando el correo'))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'💥 Error: {str(e)}'))
            import traceback
            self.stdout.write(self.style.ERROR(f'Traceback: {traceback.format_exc()}'))
