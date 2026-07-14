@echo off
setlocal

echo ============================================
echo   FixPrint.py ni .exe formatiga aylantirish
echo ============================================
echo.

REM 1) Python o'rnatilganini tekshirish
python --version >nul 2>&1
if errorlevel 1 (
    echo XATO: Python topilmadi.
    echo Avval https://www.python.org/downloads/ dan Python o'rnating
    echo ("Add python.exe to PATH" belgisini albatta yoqing^).
    pause
    exit /b 1
)

echo Python topildi, davom etilmoqda...
echo.

REM 2) PyInstaller o'rnatish (agar mavjud bo'lmasa)
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo PyInstaller o'rnatilmoqda...
    python -m pip install --upgrade pyinstaller
)

echo.
echo FixPrint.exe yasalmoqda...
echo.

REM 3) EXE yasash:
REM   --onefile      -> bitta yagona exe fayl
REM   --noconsole    -> qora konsol oynasi chiqmaydi (faqat GUI)
REM   --uac-admin    -> ishga tushirilganda avtomatik Administrator huquqi so'raydi
REM   --name         -> chiqadigan fayl nomi
python -m PyInstaller --onefile --noconsole --uac-admin --name FixPrint FixPrint.py

echo.
if exist dist\FixPrint.exe (
    echo ============================================
    echo   TAYYOR: dist\FixPrint.exe
    echo ============================================
    echo Bu faylni istalgan Windows kompyuteriga ko'chirib,
    echo ustiga ikki marta bosib ishga tushirishingiz mumkin.
    echo Python o'rnatilgan bo'lishi shart emas.
) else (
    echo XATO: exe yasalmadi. Yuqoridagi xabarlarni tekshiring.
)

echo.
pause
