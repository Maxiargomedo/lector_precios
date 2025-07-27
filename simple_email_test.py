#!/usr/bin/env python3
"""
Script simple para probar envío directo de correo
"""
import smtplib
from email.mime.text import MIMEText

def test_simple_email():
    try:
        print("🔧 Configurando correo...")
        
        # Configuración
        smtp_server = "smtp.gmail.com"
        port = 587
        sender_email = "maximilianoargomedolopez@gmail.com"
        password = "zffd fhyf bfjf mdlm"
        receiver_email = "elfarodealgarrobo2@gmail.com"
        
        # Crear mensaje simple
        message = MIMEText("Este es un correo de prueba simple desde El Faro. Si recibes esto, la configuración funciona correctamente.")
        message["Subject"] = "🧪 Prueba Simple - El Faro"
        message["From"] = sender_email
        message["To"] = receiver_email
        
        print("📡 Conectando y enviando...")
        
        # Crear sesión SMTP
        with smtplib.SMTP(smtp_server, port) as server:
            server.set_debuglevel(0)  # Sin debug para evitar spam
            server.starttls()
            server.login(sender_email, password)
            server.send_message(message)
        
        print("✅ Correo enviado exitosamente!")
        print(f"📧 De: {sender_email}")
        print(f"📧 Para: {receiver_email}")
        print("📬 Revisa la bandeja de entrada y spam de elfarodealgarrobo2@gmail.com")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == '__main__':
    print("=== PRUEBA SIMPLE DE CORREO ===")
    test_simple_email()
    print("=== FIN ===")
