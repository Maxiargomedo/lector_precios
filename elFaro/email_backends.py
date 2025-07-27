import logging
import threading
import time
import os
from datetime import datetime
from django.core.mail.backends.smtp import EmailBackend
from django.core.mail.backends.filebased import EmailBackend as FileEmailBackend
from django.conf import settings

logger = logging.getLogger(__name__)

class RobustEmailBackend(EmailBackend):
    """
    Backend de correo robusto que intenta SMTP con timeout y fallback a archivo
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.file_backend = FileEmailBackend(
            file_path=os.path.join(settings.BASE_DIR, 'emails_fallback'),
            *args, **kwargs
        )
    
    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        
        # Intentar SMTP con timeout usando threading
        try:
            logger.info("📧 Intentando envío por SMTP...")
            
            result = [None]
            exception = [None]
            
            def smtp_send():
                try:
                    result[0] = super(RobustEmailBackend, self).send_messages(email_messages)
                except Exception as e:
                    exception[0] = e
            
            # Crear y ejecutar thread con timeout
            thread = threading.Thread(target=smtp_send)
            thread.daemon = True
            thread.start()
            thread.join(timeout=15)  # 15 segundos de timeout
            
            if thread.is_alive():
                logger.warning("⏰ SMTP timeout después de 15 segundos")
                return self._send_via_fallback(email_messages, "Timeout de SMTP")
            
            if exception[0]:
                logger.warning(f"❌ Error SMTP: {exception[0]}")
                return self._send_via_fallback(email_messages, str(exception[0]))
            
            if result[0] is not None and result[0] > 0:
                logger.info(f"✅ {result[0]} correos enviados por SMTP exitosamente")
                return result[0]
            else:
                logger.warning("❌ SMTP no devolvió resultado válido")
                return self._send_via_fallback(email_messages, "SMTP sin resultado")
            
        except Exception as e:
            logger.warning(f"❌ Error general en SMTP: {e}")
            return self._send_via_fallback(email_messages, str(e))
    
    def _send_via_fallback(self, email_messages, error_reason):
        """Enviar usando método de fallback y crear log detallado"""
        try:
            logger.info("📁 Guardando correos en archivo como fallback...")
            
            # Guardar en archivo
            sent = self.file_backend.send_messages(email_messages)
            
            # Crear log detallado para correos no enviados
            log_file = os.path.join(settings.BASE_DIR, 'correos_no_enviados.log')
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"FECHA: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"RAZÓN: {error_reason}\n")
                f.write(f"{'='*60}\n")
                
                for i, message in enumerate(email_messages, 1):
                    f.write(f"\n--- CORREO {i} ---\n")
                    f.write(f"PARA: {', '.join(message.to)}\n")
                    f.write(f"ASUNTO: {message.subject}\n")
                    f.write(f"CONTENIDO:\n{message.body}\n")
                    f.write(f"{'-'*40}\n")
            
            # También crear un archivo específico para este correo
            timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            specific_file = os.path.join(settings.BASE_DIR, f'correo_pendiente_{timestamp}.txt')
            with open(specific_file, 'w', encoding='utf-8') as f:
                f.write("CORREO PENDIENTE DE ENVÍO\n")
                f.write("="*50 + "\n\n")
                f.write(f"FECHA: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"DESTINATARIO: {', '.join(email_messages[0].to)}\n")
                f.write(f"ASUNTO: {email_messages[0].subject}\n")
                f.write(f"RAZÓN DEL FALLBACK: {error_reason}\n\n")
                f.write("CONTENIDO DEL CORREO:\n")
                f.write("-" * 30 + "\n")
                f.write(email_messages[0].body)
                f.write("\n" + "-" * 30 + "\n\n")
                f.write("INSTRUCCIONES:\n")
                f.write("1. Revisa la configuración SMTP en settings.py\n")
                f.write("2. Verifica la contraseña de aplicación de Gmail\n")
                f.write("3. Copia y pega este contenido manualmente si es necesario\n")
            
            logger.info(f"✅ {sent} correos guardados en archivo")
            logger.info(f"📝 Log detallado en: {log_file}")
            logger.info(f"� Archivo específico: {specific_file}")
            
            print(f"\n⚠️  CORREO NO ENVIADO POR SMTP")
            print(f"📧 Destinatario: {', '.join(email_messages[0].to)}")
            print(f"📋 Asunto: {email_messages[0].subject}")
            print(f"📁 Guardado en: {specific_file}")
            print(f"💡 Revisa este archivo para el contenido completo del correo")
            
            return sent
            
        except Exception as file_error:
            logger.error(f"💥 Error crítico guardando correo: {file_error}")
            print(f"💥 ERROR CRÍTICO: No se pudo guardar el correo - {file_error}")
            return 0
