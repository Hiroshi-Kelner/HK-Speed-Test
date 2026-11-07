# HK Speed Test

A lightweight Windows desktop speed test built with Python and PySide6. When launched, the app opens its monochrome interface and immediately measures download speed, upload speed, and latency.

## Features

- Measures download speed, upload speed, and ping latency
- Automatically starts a speed test when the app launches
- Uses Cloudflare's public speed test endpoint
- Streams data in 64 KB chunks to reduce temporary memory usage
- No background testing or network monitoring while idle
- Simple startup integration for Windows login

## Requirements

- Windows 10 or newer
- Python 3 installed
- Internet connection for the speed test

## Quick start

1. Clone the `main` branch and enter the project folder:

   ```bat
   git clone --branch main https://github.com/Hiroshi-Kelner/HK-Speed-Test.git
   cd HK-Speed-Test
   ```

   The GitHub `/tree/main` URL opens the branch in a browser; use the repository URL above with Git.
2. Run `setup.bat`.
   - This creates a local `.venv` environment
   - Installs the dependencies from `requirements.txt`
   - If Python is not installed, the script opens the official Python download page
3. Run `run.bat` to launch the app.

## Manual usage

### Start the app

```bat
run.bat
```

`run.bat` activates the project's `.venv` and runs `main.py`. The app opens its results window and starts a test automatically. Use the button to cancel the test or run it again.

## How it works

The app connects to Cloudflare's public speed test endpoint and performs:

- a latency check
- a download test
- an upload test

During the test, it reports live progress and shows a final quality label such as:

- Slow connection
- Limited connection
- Good connection
- Very fast connection

## Notes

- Each test transfers around 35 MB total in the normal download/upload flow.
- The app does not run background tests or monitoring while closed.
- Closing the results window exits the app.

## Troubleshooting

### Python is missing

If `setup.bat` reports that Python is not found:

- install Python 3
- make sure the option `Add Python to PATH` is enabled
- rerun `setup.bat`

### Virtual environment not found

If `run.bat` says the virtual environment does not exist:

```bat
setup.bat
```

### App does not launch

Make sure the project folder contains a valid `.venv` and that dependencies were installed successfully before starting the app.

## License

This project is intended for personal use and local testing. See the repository for the current licensing details if applicable.
