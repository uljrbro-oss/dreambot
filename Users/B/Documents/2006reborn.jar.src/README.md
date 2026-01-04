# RS2 Game Client - Build Instructions

This is a decompiled Java 8 RS2 game client project that has been fixed for compilation.

## Fixed Issues

The following decompiler artifacts and syntax errors have been resolved:

1. **rs2/Censor.java**: Added missing closing braces that caused "reached end of file while parsing" error
2. **rs2/client.java**: Removed stray `this;` statements at lines 6607, 6609, and 12089
3. **rs2/Class13.java**: 
   - Added missing closing brace for method227
   - Fixed undefined variables (byte9, byte10, byte11) by declaring them and initializing with method228 calls
4. **rs2/sign/signlink.java**: Added missing import statements for Applet, MIDI, and Audio APIs

## Building the Project

### Prerequisites
- Java Development Kit (JDK) 8 or compatible version with Java 8 source/target support

### Compile and Build JAR

```bash
# Navigate to the project directory
cd Users/B/Documents/2006reborn.jar.src

# Create sources list (if needed)
find . -name "*.java" -type f > sources.lst

# Compile all Java files
javac -source 1.8 -target 1.8 -encoding UTF-8 -d out/classes @sources.lst

# Create runnable JAR
jar cfm out/2006reborn.jar META-INF/MANIFEST.MF -C out/classes .
```

### Running the Application

```bash
# Run the JAR file
java -cp out/2006reborn.jar rs2.Main

# On Windows PowerShell (with native libraries):
java -cp "out\2006reborn.jar;lib\*" "-Djava.library.path=win-x64" rs2.Main

# On Linux:
java -cp "out/2006reborn.jar:lib/*" -Djava.library.path=linux rs2.Main

# On macOS:
java -cp "out/2006reborn.jar:lib/*" -Djava.library.path=darwin rs2.Main
```

## Project Structure

```
2006reborn.jar.src/
├── META-INF/
│   └── MANIFEST.MF          # JAR manifest with Main-Class entry
├── rs2/
│   ├── Main.java            # Application entry point
│   ├── client.java          # Main client class
│   ├── Censor.java          # Text censoring functionality
│   ├── Class13.java         # Binary data processing
│   └── sign/
│       └── signlink.java    # Audio and network utilities
├── lib/                     # External JAR dependencies
├── win-x64/                 # Windows x64 native libraries
├── win-x86/                 # Windows x86 native libraries
├── linux/                   # Linux native libraries
├── darwin/                  # macOS native libraries
└── out/                     # Build output (excluded from git)
    ├── classes/             # Compiled .class files
    └── 2006reborn.jar       # Final JAR file
```

## Notes

- The project uses Java 8 compatibility (`-source 1.8 -target 1.8`)
- Some deprecation warnings about `java.applet.Applet` are expected (deprecated in Java 9+)
- Build artifacts (`.class` files and `out/` directory) are excluded from version control via `.gitignore`
