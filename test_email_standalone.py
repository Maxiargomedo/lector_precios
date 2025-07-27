#!/usr/bin/env python3
"""
Script de prueba independiente para verificar envío de correos
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Configuración de correo
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_HOST_USER = 'maximilianoargomedolopez@gmail.com'
EMAIL_HOST_PASSWORD = 'zffd fhyf bfjf mdlm'  # Nueva contraseña: lector_elFaro_Final
ADMIN_EMAIL = 'elfarodealgarrobo2@gmail.com'

def test_smtp_connection():
    """Probar conexión SMTP básica"""
    try:
        print("🔌 Conectando al servidor SMTP...")
        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        
        print("🔐 Iniciando TLS...")
        server.starttls()
        
        print("🔑 Autenticando...")
        server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
        
        print("✅ Conexión SMTP exitosa")
        server.quit()
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ Error de autenticación: {e}")
        print("💡 Verifica que:")
        print("   - La autenticación de 2 factores esté activada en Gmail")
        print("   - Estés usando una contraseña de aplicación (no tu contraseña normal)")
        print("   - La contraseña de aplicación sea correcta")
        return False
        
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        return False

def send_test_email():
    """Enviar correo de prueba"""
    try:
        print("\n📧 Preparando correo de prueba...")
        
        # Crear mensaje
        msg = MIMEMultipart()
        msg['From'] = EMAIL_HOST_USER
        msg['To'] = ADMIN_EMAIL
        msg['Subject'] = '🧪 Prueba de correo - El Faro (Script independiente)'
        
        body = """Este es un correo de prueba enviado desde un script independiente.

Si recibes este correo, significa que la configuración SMTP está funcionando correctamente.

🔧 Configuración utilizada:
- Servidor: smtp.gmail.com:587
- Usuario: maximilianoargomedolopez@gmail.com
- Destino: elfarodealgarrobo2@gmail.com

El problema anterior puede estar en Django o en la configuración del proyecto."""
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Enviar con timeout
        print("📧 Conectando para envío...")
        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=30)
        server.starttls()
        
        print("📧 Autenticando para envío...")
        server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
        
        print("📧 Enviando mensaje...")
        text = msg.as_string()
        server.sendmail(EMAIL_HOST_USER, ADMIN_EMAIL, text)
        
        print("📧 Cerrando conexión...")
        server.quit()
        
        print("✅ Correo enviado exitosamente")
        print(f"📧 Desde: {EMAIL_HOST_USER}")
        print(f"📧 Hacia: {ADMIN_EMAIL}")
        return True
        
    except Exception as e:
        print(f"❌ Error enviando correo: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return False

if __name__ == '__main__':
    print("=== PRUEBA DE CORREO INDEPENDIENTE ===\n")
    
    # Paso 1: Probar conexión
    if test_smtp_connection():
        # Paso 2: Enviar correo
        send_test_email()
    else:
        print("\n💡 Soluciones recomendadas:")
        print("1. Verifica que tengas activada la autenticación de 2 factores en Gmail")
        print("2. Genera una nueva contraseña de aplicación en Gmail")
        print("3. Usa esa contraseña de aplicación en lugar de tu contraseña normal")
        print("4. Asegúrate de que el acceso a apps menos seguras esté permitido")
    
    print("\n=== FIN DE LA PRUEBA ===")
