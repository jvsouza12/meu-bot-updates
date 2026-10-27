@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

title Build - AUTO By ]BETANO

if /I not "%OS%"=="Windows_NT" (
    echo ERRO: este script deve ser executado no Windows.
    exit /b 1
)

echo.
echo ==========================================
echo       BUILD - AUTO By ]BETANO
echo ==========================================
echo.

where py >nul 2>nul

if errorlevel 1 (
    echo ERRO: Python nao foi encontrado no PATH.
    echo Instale Python 3.11 ou mais recente.
    exit /b 1
)

if not exist "app.py" (
    echo ERRO: app.py nao foi encontrado na raiz do projeto.
    exit /b 1
)

if not exist "src\interface.py" (
    echo ERRO: src\interface.py nao foi encontrado.
    exit /b 1
)

if not exist "src\updater.py" (
    echo ERRO: src\updater.py nao foi encontrado.
    exit /b 1
)

if not exist "assets" (
    echo ERRO: a pasta assets nao foi encontrada.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo === Criando ambiente virtual ===

    py -3 -m venv .venv

    if errorlevel 1 (
        echo ERRO: nao foi possivel criar o ambiente virtual.
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"

if errorlevel 1 (
    echo ERRO: nao foi possivel ativar o ambiente virtual.
    exit /b 1
)

echo.
echo === Atualizando o pip ===

python -m pip install --upgrade pip

if errorlevel 1 (
    echo ERRO: falha ao atualizar o pip.
    exit /b 1
)

echo.
echo === Instalando dependencias ===

if not exist "requirements.txt" (
    echo ERRO: requirements.txt nao foi encontrado.
    exit /b 1
)

python -m pip install -r requirements.txt

if errorlevel 1 (
    echo ERRO: falha ao instalar as dependencias.
    exit /b 1
)

echo.
echo === Verificando a sintaxe Python ===

python -m py_compile app.py

if errorlevel 1 (
    echo ERRO: falha na compilacao de app.py.
    exit /b 1
)

python -m py_compile src\*.py

if errorlevel 1 (
    echo ERRO: falha na compilacao dos arquivos Python.
    exit /b 1
)

echo Sintaxe Python validada com sucesso.

if exist "tests" (
    echo.
    echo === Executando testes ===

    python -m pip install pytest

    if errorlevel 1 (
        echo ERRO: nao foi possivel instalar o pytest.
        exit /b 1
    )

    python -m pytest -q

    if errorlevel 1 (
        echo ERRO: os testes falharam.
        echo A compilacao foi cancelada.
        exit /b 1
    )
) else (
    echo.
    echo Nenhuma pasta tests encontrada.
    echo Testes automaticos ignorados.
)

echo.
echo === Limpando artefatos anteriores ===

if exist "build" (
    rmdir /s /q "build"
)

if exist "dist" (
    rmdir /s /q "dist"
)

if exist "AUTO_By_BETANO_DISTRIBUICAO" (
    rmdir /s /q "AUTO_By_BETANO_DISTRIBUICAO"
)

mkdir "dist"
mkdir "AUTO_By_BETANO_DISTRIBUICAO"

if errorlevel 1 (
    echo ERRO: nao foi possivel criar as pastas de build.
    exit /b 1
)

echo.
echo === Compilando AUTO By ]BETANO.exe ===

python -m PyInstaller ^
    --clean ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "AUTO By ]BETANO" ^
    --add-data "assets;assets" ^
    --icon "assets\icon.ico" ^
    app.py

if errorlevel 1 (
    echo ERRO: o PyInstaller falhou.
    exit /b 1
)

if not exist "dist\AUTO By ]BETANO.exe" (
    echo ERRO: AUTO By ]BETANO.exe nao foi gerado.
    exit /b 1
)

echo.
echo === Montando pacote de distribuicao ===

copy /y ^
    "dist\AUTO By ]BETANO.exe" ^
    "AUTO_By_BETANO_DISTRIBUICAO\AUTO By ]BETANO.exe" ^
    >nul

if errorlevel 1 (
    echo ERRO: nao foi possivel copiar o executavel.
    exit /b 1
)

if exist "README_USUARIO.txt" (
    copy /y ^
        "README_USUARIO.txt" ^
        "AUTO_By_BETANO_DISTRIBUICAO\README_USUARIO.txt" ^
        >nul

    if errorlevel 1 (
        echo ERRO: nao foi possivel copiar o README_USUARIO.txt.
        exit /b 1
    )
) else (
    echo AVISO: README_USUARIO.txt nao encontrado.
    echo O pacote sera gerado sem esse arquivo.
)

echo.
echo === Gerando hash SHA-256 ===

certutil -hashfile ^
    "AUTO_By_BETANO_DISTRIBUICAO\AUTO By ]BETANO.exe" ^
    SHA256 ^
    > "AUTO_By_BETANO_DISTRIBUICAO\SHA256SUMS.txt"

if errorlevel 1 (
    echo ERRO: nao foi possivel gerar o hash SHA-256.
    exit /b 1
)

echo.
echo ==========================================
echo COMPILACAO CONCLUIDA COM SUCESSO
echo ==========================================
echo.
echo Executavel gerado:
echo dist\AUTO By ]BETANO.exe
echo.
echo Pacote de distribuicao:
echo AUTO_By_BETANO_DISTRIBUICAO
echo.
echo Arquivos do pacote:
echo - AUTO By ]BETANO.exe
echo - README_USUARIO.txt, se existir
echo - SHA256SUMS.txt
echo.

endlocal
exit /b 0
