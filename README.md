# Speed Test

A small, dark monochrome PySide6 system-tray speed test. It stays idle until you
click its tray icon; that click opens the results window and starts a test.
Right-click the icon to run a test, show the window, or quit.

## Set up on Windows

Run `setup.bat` to create the `.venv` virtual environment and install the
dependencies from `requirements.txt`. Python 3 must be installed; if it is
missing, the script opens the Python downloads page. Install Python with
**Add Python to PATH** enabled, then run `setup.bat` again.

Run `run.bat` to activate the virtual environment and launch `main.py`. Run
`startup.bat` once to add the app to your Windows startup apps; it creates a
shortcut so the app launches when you sign in.

Each test uses Cloudflare's public speed-test endpoint and transfers up to
about 35 MB. The app does not test, monitor, or send network requests in the
background. Download data and upload payloads are streamed in 64 KB chunks to
keep temporary memory use low; Python and Qt still have their normal idle
runtime overhead.

The tray tooltip summarizes the measured connection after a successful test.
