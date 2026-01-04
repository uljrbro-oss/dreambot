@echo off
REM Build script for RS2 Game Client (Windows)

echo Building RS2 Game Client...
echo ==============================

REM Clean previous build
echo Cleaning previous build...
if exist out rmdir /s /q out
mkdir out\classes

REM Create sources list
echo Creating sources list...
dir /s /b *.java > sources.lst

REM Compile
echo Compiling Java sources...
javac -source 1.8 -target 1.8 -encoding UTF-8 -d out\classes @sources.lst
if %errorlevel% neq 0 (
    echo Compilation failed!
    exit /b 1
)

REM Create JAR
echo Creating JAR file...
jar cfm out\2006reborn.jar META-INF\MANIFEST.MF -C out\classes .
if %errorlevel% neq 0 (
    echo JAR creation failed!
    exit /b 1
)

echo ==============================
echo Build successful!
echo JAR file created at: out\2006reborn.jar
echo.
echo To run the application:
echo   java -cp out\2006reborn.jar rs2.Main
echo.
echo With native libraries (PowerShell):
echo   java -cp "out\2006reborn.jar;lib\*" "-Djava.library.path=win-x64" rs2.Main
