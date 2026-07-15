@echo off
:: ============================================================================
::  FixPrint - Yagona BAT fayl
::
::  1) Point and Print Restrictions tezkor tuzatish (Python shart emas)
::  2) FixPrint.exe yasash (PyInstaller orqali)
::
::  Created by Javohir Hojibayev
:: ============================================================================
setlocal enabledelayedexpansion

:: Administrator tekshiruvi
net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [XATO] Bu skript Administrator huquqi bilan ishga tushirilishi kerak!
    echo         Sichqonchaning o'ng tugmasini bosib "Run as administrator" tanlang.
    echo.
    pause
    exit /b 1
)

title FixPrint
color 0A

:MENU
cls
echo.
echo  ==============================================================
echo   FixPrint - Printer muammolarini tuzatish
echo  ==============================================================
echo   Kompyuter: %COMPUTERNAME%
echo   Foydalanuvchi: %USERNAME%
echo  ==============================================================
echo.
echo   [1] Tezkor tuzatish (Point and Print siyosatini tuzatish)
echo       Python talab qilmaydi. Registryni tuzatadi va Spooler
echo       ni qayta ishga tushiradi.
echo.
echo   [2] FixPrint.exe yasash (PyInstaller orqali)
echo       To'liq GUI dasturni .exe formatiga aylantiradi.
echo       Python o'rnatilgan bo'lishi kerak.
echo.
echo   [0] Chiqish
echo.
echo  ==============================================================
echo.
set /p choice="  Tanlovingiz (0/1/2): "

if "%choice%"=="1" goto FIX
if "%choice%"=="2" goto BUILD
if "%choice%"=="0" exit /b 0
echo.
echo  [!] Noto'g'ri tanlov. Qaytadan urinib ko'ring.
timeout /t 2 /nobreak >nul
goto MENU


:: ===================================================================
:: 1-VARIANT: TEZKOR TUZATISH
:: ===================================================================
:FIX
cls
echo.
echo  ==============================================================
echo   FixPrint - Point and Print Restrictions siyosatini tuzatish
echo  ==============================================================
echo   Kompyuter: %COMPUTERNAME%
echo   Sana: %DATE% %TIME%
echo  ==============================================================
echo.

echo  == 1-QISM: PointAndPrint registry sozlamalari ==
echo.

reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PointAndPrint" /v RestrictDriverInstallationToAdministrators /t REG_DWORD /d 0 /f >nul 2>&1
if %errorlevel%==0 (echo   [OK] RestrictDriverInstallationToAdministrators = 0) else (echo   [!] RestrictDriverInstallationToAdministrators xato)

reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PointAndPrint" /v TrustedServers /t REG_DWORD /d 0 /f >nul 2>&1
if %errorlevel%==0 (echo   [OK] TrustedServers = 0) else (echo   [!] TrustedServers xato)

reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PointAndPrint" /v InForest /t REG_DWORD /d 0 /f >nul 2>&1
if %errorlevel%==0 (echo   [OK] InForest = 0) else (echo   [!] InForest xato)

reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PointAndPrint" /v NoWarningNoElevationOnInstall /t REG_DWORD /d 1 /f >nul 2>&1
if %errorlevel%==0 (echo   [OK] NoWarningNoElevationOnInstall = 1) else (echo   [!] NoWarningNoElevationOnInstall xato)

reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PointAndPrint" /v UpdatePromptSettings /t REG_DWORD /d 0 /f >nul 2>&1
if %errorlevel%==0 (echo   [OK] UpdatePromptSettings = 0) else (echo   [!] UpdatePromptSettings xato)

reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PointAndPrint" /v Restricted /t REG_DWORD /d 0 /f >nul 2>&1
if %errorlevel%==0 (echo   [OK] Restricted = 0) else (echo   [!] Restricted xato)

echo.
echo  == 2-QISM: PackagePointAndPrint registry sozlamalari ==
echo.

reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PackagePointAndPrint" /v PackagePointAndPrintOnly /t REG_DWORD /d 0 /f >nul 2>&1
if %errorlevel%==0 (echo   [OK] PackagePointAndPrintOnly = 0) else (echo   [!] PackagePointAndPrintOnly xato)

reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\PackagePointAndPrint" /v PackagePointAndPrintServerList /t REG_DWORD /d 0 /f >nul 2>&1
if %errorlevel%==0 (echo   [OK] PackagePointAndPrintServerList = 0) else (echo   [!] PackagePointAndPrintServerList xato)

echo.
echo  == 3-QISM: Qo'shimcha RPC va printer siyosat sozlamalari ==
echo.

reg add "HKLM\System\CurrentControlSet\Control\Print" /v RpcAuthnLevelPrivacyEnabled /t REG_DWORD /d 0 /f >nul 2>&1
if %errorlevel%==0 (echo   [OK] RpcAuthnLevelPrivacyEnabled = 0) else (echo   [!] RpcAuthnLevelPrivacyEnabled xato)

reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\RPC" /v RpcAuthnLevelPrivacyEnabled /t REG_DWORD /d 0 /f >nul 2>&1
if %errorlevel%==0 (echo   [OK] RPC\RpcAuthnLevelPrivacyEnabled = 0) else (echo   [!] RPC\RpcAuthnLevelPrivacyEnabled xato)

reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\RPC" /v RpcUseNamedPipeProtocol /t REG_DWORD /d 1 /f >nul 2>&1
if %errorlevel%==0 (echo   [OK] RpcUseNamedPipeProtocol = 1) else (echo   [!] RpcUseNamedPipeProtocol xato)

reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\RPC" /v RpcProtocols /t REG_DWORD /d 7 /f >nul 2>&1
if %errorlevel%==0 (echo   [OK] RpcProtocols = 7) else (echo   [!] RpcProtocols xato)

reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers\RPC" /v ForceKerberosForRpc /t REG_DWORD /d 0 /f >nul 2>&1
if %errorlevel%==0 (echo   [OK] ForceKerberosForRpc = 0) else (echo   [!] ForceKerberosForRpc xato)

reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers" /v DisableWebPnPDownload /t REG_DWORD /d 0 /f >nul 2>&1
if %errorlevel%==0 (echo   [OK] DisableWebPnPDownload = 0) else (echo   [!] DisableWebPnPDownload xato)

reg add "HKLM\Software\Policies\Microsoft\Windows NT\Printers" /v DisableHTTPPrinting /t REG_DWORD /d 0 /f >nul 2>&1
if %errorlevel%==0 (echo   [OK] DisableHTTPPrinting = 0) else (echo   [!] DisableHTTPPrinting xato)

echo.
echo  == 4-QISM: Print Spooler qayta ishga tushirish ==
echo.

echo   Spooler to'xtatilmoqda...
net stop Spooler >nul 2>&1
timeout /t 2 /nobreak >nul

echo   Spooler ishga tushirilmoqda...
net start Spooler >nul 2>&1
timeout /t 2 /nobreak >nul

sc query Spooler | find "RUNNING" >nul 2>&1
if %errorlevel%==0 (
    echo   [OK] Print Spooler muvaffaqiyatli qayta ishga tushdi
) else (
    echo   [!] Print Spooler ishga tushmadi. Qo'lda tekshiring: services.msc
)

echo.
echo  ==============================================================
echo   TAYYOR!
echo  ==============================================================
echo.
echo   Shu kompyuterda printer ulanishi darhol ishlashi kerak.
echo.
echo   Agar muammo davom etsa:
echo     1. Kompyuterni qayta yoqing (shutdown /r /t 0)
echo     2. FixPrint.exe dasturini ishga tushiring (to'liq tuzatish)
echo.
echo  ==============================================================
echo.
pause
goto MENU


:: ===================================================================
:: 2-VARIANT: EXE YASASH
:: ===================================================================
:BUILD
cls
echo.
echo  ============================================
echo   FixPrint.py ni .exe formatiga aylantirish
echo  ============================================
echo.

REM Python o'rnatilganini tekshirish
python --version >nul 2>&1
if errorlevel 1 (
    echo  [XATO] Python topilmadi.
    echo  Avval https://www.python.org/downloads/ dan Python o'rnating
    echo  ("Add python.exe to PATH" belgisini albatta yoqing^).
    echo.
    pause
    goto MENU
)

echo  Python topildi, davom etilmoqda...
echo.

REM PyInstaller o'rnatish (agar mavjud bo'lmasa)
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo  PyInstaller o'rnatilmoqda...
    python -m pip install --upgrade pyinstaller
)

echo.
echo  FixPrint.exe yasalmoqda...
echo.

REM EXE yasash (ikonka bilan yoki ikonkasiz)
if exist fixprint.ico (
    echo  Ikonka fayli topildi: fixprint.ico
    python -m PyInstaller --onefile --noconsole --uac-admin --name FixPrint --icon=fixprint.ico FixPrint.py
) else (
    echo  Ikonka fayli topilmadi, ikonkasiz yasalmoqda...
    python -m PyInstaller --onefile --noconsole --uac-admin --name FixPrint FixPrint.py
)

echo.
if exist dist\FixPrint.exe (
    copy /Y dist\FixPrint.exe FixPrint.exe >nul 2>&1

    REM Build papkalarini tozalash
    rmdir /S /Q build >nul 2>&1
    rmdir /S /Q dist >nul 2>&1
    del /Q FixPrint.spec >nul 2>&1

    echo  ============================================
    echo   TAYYOR: FixPrint.exe
    echo  ============================================
    echo.
    echo  Bu faylni istalgan Windows kompyuteriga ko'chirib,
    echo  ustiga ikki marta bosib ishga tushirishingiz mumkin.
    echo  Python o'rnatilgan bo'lishi shart emas.
) else (
    echo  [XATO] exe yasalmadi. Yuqoridagi xabarlarni tekshiring.
)

echo.
pause
goto MENU
