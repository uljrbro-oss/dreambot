#!/bin/bash
# Build script for RS2 Game Client

set -e  # Exit on error

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "Building RS2 Game Client..."
echo "=============================="

# Clean previous build
echo "Cleaning previous build..."
rm -rf out
mkdir -p out/classes

# Create sources list
echo "Creating sources list..."
find . -name "*.java" -type f > sources.lst

# Compile
echo "Compiling Java sources..."
javac -source 1.8 -target 1.8 -encoding UTF-8 -d out/classes @sources.lst

# Create JAR
echo "Creating JAR file..."
jar cfm out/2006reborn.jar META-INF/MANIFEST.MF -C out/classes .

echo "=============================="
echo "Build successful!"
echo "JAR file created at: out/2006reborn.jar"
echo ""
echo "To run the application:"
echo "  java -cp out/2006reborn.jar rs2.Main"
