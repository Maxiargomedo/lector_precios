from waitress import serve
from mi_proyecto.wsgi import application
import socket
import os
import sys
import time
from zeroconf import ServiceInfo, Zeroconf

# Asegurarnos que estamos en el directorio correcto del proyecto
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Agregar la ruta del proyecto al sys.path si no está ya
project_path = os.path.dirname(os.path.abspath(__file__))
if project_path not in sys.path:
    sys.path.append(project_path)

def get_local_ip():
    """Obtiene la IP local del servidor"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Conecta a Google DNS para determinar la interfaz de salida
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return '127.0.0.1'

def register_mdns_service(ip, port, name="elfaro"):
    """Registra el servicio mDNS para ser descubierto en la red local"""
    try:
        hostname = socket.gethostname().lower()
        service_name = f"{name}.local."
        info = ServiceInfo(
            "_http._tcp.local.",
            f"{name}._http._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=port,
            properties={"path": "/"},
            server=f"{hostname}.local."
        )
        
        zeroconf = Zeroconf()
        zeroconf.register_service(info)
        print(f"* Servicio mDNS: http://{name}.local:{port}")
        return zeroconf, info
    except Exception as e:
        print(f"No se pudo registrar servicio mDNS: {e}")
        return None, None

if __name__ == '__main__':
    ip = get_local_ip()
    puerto = 8000
    
    print(f"\n{'='*60}")
    print(f"Servidor Django iniciado en http://{ip}:{puerto}")
    print(f"DIRECCIONES DE ACCESO:")
    print(f"  * Local:   http://localhost:{puerto}")
    print(f"  * Red LAN: http://{ip}:{puerto} (desde otros dispositivos)")
    
    # Registrar servicio mDNS
    zeroconf, info = register_mdns_service(ip, puerto)
    
    print(f"{'='*60}\n")
    
    try:
        # Iniciamos el servidor con 4 hilos para manejar múltiples conexiones
        serve(application, host='0.0.0.0', port=puerto, threads=4)
    except KeyboardInterrupt:
        print("\nServidor detenido por el usuario.")
    finally:
        # Limpiar registro mDNS al salir
        if zeroconf and info:
            try:
                zeroconf.unregister_service(info)
                zeroconf.close()
                print("Servicio mDNS desregistrado.")
            except:
                pass