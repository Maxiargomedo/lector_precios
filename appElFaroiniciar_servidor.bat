@echo off
title El Faro - Servidor HTTPS Automático
color 0A

cls
echo.
echo ==========================================
echo     EL FARO - INICIANDO AUTOMÁTICO
echo ==========================================
echo.

REM Activar entorno virtual si existe
if exist "venv\Scripts\activate.bat" (
    echo [INFO] Activando entorno virtual...
    call venv\Scripts\activate.bat
    echo ✅ Entorno virtual activado
) else (
    echo [INFO] Usando Python del sistema
)

REM Verificar e instalar dependencias automáticamente
echo.
echo [PASO 1/6] Verificando dependencias...
cd C:\appElFaro

REM Instalar django_extensions si no está
echo • Verificando django_extensions...
C:\Users\gonza\AppData\Local\Programs\Python\Python313\python.exe -c "import django_extensions; print('✅ django_extensions OK')" 2>nul
if errorlevel 1 (
    echo   ⚠️ No encontrado, instalando...
    C:\Users\gonza\AppData\Local\Programs\Python\Python313\python.exe -m pip install django_extensions
    if errorlevel 0 (
        echo   ✅ django_extensions instalado
    ) else (
        echo   ❌ Error instalando django_extensions
    )
) else (
    echo   ✅ django_extensions ya instalado
)

REM Instalar Werkzeug si no está
echo • Verificando Werkzeug...
C:\Users\gonza\AppData\Local\Programs\Python\Python313\python.exe -c "import werkzeug; print('✅ Werkzeug OK')" 2>nul
if errorlevel 1 (
    echo   ⚠️ No encontrado, instalando...
    C:\Users\gonza\AppData\Local\Programs\Python\Python313\python.exe -m pip install Werkzeug
    if errorlevel 0 (
        echo   ✅ Werkzeug instalado
    ) else (
        echo   ❌ Error instalando Werkzeug
    )
) else (
    echo   ✅ Werkzeug ya instalado
)

REM Habilitar django_extensions en settings.py
echo.
echo [PASO 2/6] Configurando Django...
echo • Verificando configuración de settings.py...

REM Descomentar django_extensions si está comentado
powershell -Command "(Get-Content mi_proyecto\settings.py) -replace '#''django_extensions'',', '    ''django_extensions'',' | Set-Content mi_proyecto\settings.py"

REM Verificar si ya está habilitado
findstr /C:"'django_extensions'," mi_proyecto\settings.py >nul
if errorlevel 1 (
    echo   ⚠️ django_extensions no encontrado en INSTALLED_APPS
    echo   ➕ Agregando automáticamente...
    powershell -Command "(Get-Content mi_proyecto\settings.py) -replace '    ''elFaro'',', '    ''elFaro'',\n    ''django_extensions'',' | Set-Content mi_proyecto\settings.py"
    echo   ✅ django_extensions agregado a INSTALLED_APPS
) else (
    echo   ✅ django_extensions ya está en INSTALLED_APPS
)

REM Verificar ngrok
echo.
echo [PASO 3/6] Verificando ngrok...
if exist "C:\ngrok\ngrok.exe" (
    echo ✅ ngrok encontrado en C:\ngrok\ngrok.exe
) else (
    echo ❌ ngrok NO encontrado en C:\ngrok\ngrok.exe
    echo.
    echo 🔧 INSTRUCCIONES PARA INSTALAR NGROK:
    echo    1. Ve a https://ngrok.com
    echo    2. Crea cuenta gratuita
    echo    3. Descarga ngrok para Windows
    echo    4. Extrae ngrok.exe a C:\ngrok\
    echo    5. Vuelve a ejecutar este archivo
    echo.
    echo 💡 Sin ngrok, la cámara NO funcionará
    echo    Pero puedes usar HTTP normal en http://127.0.0.1:8000/
    echo.
    pause
    goto solo_django
)

REM Detener procesos previos
echo.
echo [PASO 4/6] Limpiando procesos anteriores...
echo • Cerrando Django anterior...
taskkill /f /im python.exe >nul 2>&1
if errorlevel 0 (
    echo   ✅ Procesos Python cerrados
) else (
    echo   ℹ️ No había procesos Python corriendo
)

echo • Cerrando ngrok anterior...
taskkill /f /im ngrok.exe >nul 2>&1
if errorlevel 0 (
    echo   ✅ Procesos ngrok cerrados
) else (
    echo   ℹ️ No había procesos ngrok corriendo
)

echo • Esperando limpieza...
timeout /t 2 /nobreak >nul
echo   ✅ Limpieza completada

REM Iniciar Django
echo.
echo [PASO 5/6] Iniciando Django...
echo • Lanzando servidor Django...
start "🌐 Django - El Faro" cmd /k "title 🌐 Django Server - El Faro && color 0A && echo. && echo ========================================== && echo       🌐 DJANGO SERVER - EL FARO && echo ========================================== && echo. && echo ⏳ Iniciando servidor Django... && echo. && cd C:\appElFaro && C:\Users\gonza\AppData\Local\Programs\Python\Python313\python.exe servidor.py"

echo   ✅ Ventana de Django abierta
echo   ⏳ Esperando que Django inicie completamente...

REM Esperar que Django inicie (con contador visual)
for /L %%i in (5,-1,1) do (
    echo      Esperando %%i segundos...
    timeout /t 1 /nobreak >nul
)

REM Iniciar ngrok
echo.
echo [PASO 6/6] Iniciando ngrok...
echo • Lanzando ngrok HTTPS...
start "📷 ngrok HTTPS - El Faro" cmd /k "title 📷 ngrok HTTPS - El Faro && color 0C && echo. && echo ========================================== && echo      📷 NGROK HTTPS - EL FARO && echo ========================================== && echo. && echo ⏳ Generando URL HTTPS segura... && echo 📱 Para usar la CÁMARA, copia la URL HTTPS && echo    que aparece abajo (https://xxxxx.ngrok.io) && echo. && echo 🔄 Iniciando túnel seguro... && echo ========================================== && echo. && C:\ngrok\ngrok.exe http 8000"

echo   ✅ Ventana de ngrok abierta
echo   ⏳ Esperando que ngrok genere URL...
timeout /t 3 /nobreak >nul

goto mostrar_resultado

:solo_django
echo.
echo [PASO 4/4] Iniciando solo Django (sin ngrok)...
echo • Cerrando procesos anteriores...
taskkill /f /im python.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo • Lanzando Django...
start "🌐 Django - El Faro" cmd /k "title 🌐 Django HTTP - El Faro && color 0A && echo. && echo ========================================== && echo       🌐 DJANGO HTTP - EL FARO && echo ========================================== && echo. && echo ⚠️  MODO SOLO HTTP - CÁMARA NO FUNCIONA && echo 🌍 Accede desde: http://127.0.0.1:8000/ && echo. && echo ⏳ Iniciando servidor... && echo ========================================== && echo. && cd C:\appElFaro && C:\Users\gonza\AppData\Local\Programs\Python\Python313\python.exe servidor.py"

echo   ✅ Django iniciado en modo HTTP
timeout /t 3 /nobreak >nul

echo.
echo ==========================================
echo        🚀 ¡DJANGO INICIADO! 🚀
echo ==========================================
echo.
echo ✅ Django HTTP: http://127.0.0.1:8000/
echo ❌ ngrok: No disponible
echo.
echo ⚠️  LIMITACIONES SIN NGROK:
echo    • La cámara NO funcionará
echo    • Solo acceso desde esta PC
echo    • Funciones normales SÍ funcionan
echo.
goto menu_control

:mostrar_resultado
cls
echo.
echo ==========================================
echo        🚀 ¡EL FARO INICIADO! 🚀
echo ==========================================
echo.
echo ✅ Django HTTP:     http://127.0.0.1:8000/
echo ✅ ngrok HTTPS:     Revisa la ventana de ngrok
echo.
echo 📱 PARA USAR LA CÁMARA:
echo    1. Ve a la ventana de ngrok (roja)
echo    2. Busca la línea: Forwarding https://xxxxx.ngrok.io
echo    3. Copia esa URL HTTPS
echo    4. Úsala en cualquier dispositivo
echo    5. Haz clic en el botón de cámara 📷
echo.
echo 🌍 PARA USO NORMAL (sin cámara):
echo    Usa: http://127.0.0.1:8000/
echo.
echo 💡 AMBAS VENTANAS DEBEN MANTENERSE ABIERTAS
echo.

:menu_control
echo ==========================================
echo           🎛️ PANEL DE CONTROL
echo ==========================================
echo.
echo [1] Ver este resumen nuevamente
echo [2] Abrir http://127.0.0.1:8000/ en navegador
echo [3] Verificar estado de servidores
echo [4] Reiniciar todo
echo [5] Detener todos los servidores
echo [6] Salir (mantener servidores corriendo)
echo.
set /p accion="🎯 ¿Qué quieres hacer? (1-6): "

if "%accion%"=="1" goto mostrar_resultado
if "%accion%"=="2" goto abrir_navegador
if "%accion%"=="3" goto verificar_estado
if "%accion%"=="4" goto reiniciar_todo
if "%accion%"=="5" goto detener_todo
if "%accion%"=="6" goto salir_sin_detener

echo.
echo ❌ Opción inválida. Intenta de nuevo...
timeout /t 2 /nobreak >nul
goto menu_control

:abrir_navegador
echo.
echo 🌐 Abriendo http://127.0.0.1:8000/ en el navegador...
start http://127.0.0.1:8000/
echo ✅ Navegador abierto
timeout /t 2 /nobreak >nul
goto menu_control

:verificar_estado
echo.
echo 🔍 Verificando estado de servidores...
echo.

REM Verificar Django
netstat -an | findstr ":8000" >nul
if errorlevel 0 (
    echo ✅ Django: Corriendo en puerto 8000
) else (
    echo ❌ Django: NO detectado en puerto 8000
)

REM Verificar ngrok
tasklist | findstr "ngrok.exe" >nul
if errorlevel 0 (
    echo ✅ ngrok: Proceso corriendo
) else (
    echo ❌ ngrok: Proceso NO encontrado
)

echo.
echo 💡 Si hay problemas, usa la opción 4 para reiniciar
echo.
pause
goto menu_control

:reiniciar_todo
echo.
echo 🔄 Reiniciando todos los servidores...
echo • Deteniendo procesos...
taskkill /f /im python.exe >nul 2>&1
taskkill /f /im ngrok.exe >nul 2>&1
echo • Esperando limpieza...
timeout /t 3 /nobreak >nul
echo ✅ Reiniciando...
goto inicio

:detener_todo
echo.
echo 🛑 Deteniendo todos los servidores...
echo • Cerrando Django...
taskkill /f /im python.exe >nul 2>&1
echo • Cerrando ngrok...
taskkill /f /im ngrok.exe >nul 2>&1
echo • Cerrando ventanas adicionales...
taskkill /f /fi "WINDOWTITLE:*Django*El Faro*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE:*ngrok*El Faro*" >nul 2>&1
echo.
echo ✅ Todos los servidores detenidos correctamente
echo.
timeout /t 3 /nobreak >nul
exit

:salir_sin_detener
echo.
echo 🚀 Los servidores siguen corriendo en segundo plano
echo 💡 Cierra las ventanas manualmente si quieres detenerlos
echo 📱 Recuerda: USA LA URL HTTPS DE NGROK PARA LA CÁMARA
echo.
timeout /t 3 /nobreak >nul
exit