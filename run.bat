@echo off
echo Starting Model Manager...
echo.

REM Check if virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found at venv\Scripts\activate.bat
    echo Please create a virtual environment by running: python -m venv venv
    echo Then install dependencies: venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate

REM Check if main.py exists
if not exist "main.py" (
    echo ERROR: main.py not found in current directory
    pause
    exit /b 1
)

REM Run the Python application
echo Running Model Manager application...
python main.py

REM Deactivate virtual environment when done
deactivate

echo.
echo Application finished.
pause