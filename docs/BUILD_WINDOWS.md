# Building the Windows executable

The release was prepared on Linux, which cannot produce a Windows `.exe` with PyInstaller (PyInstaller only
builds for the operating system it runs on). These are the exact steps to produce and check the executable on
a Windows PC. The build script stops at the first failure and only prints `BUILD SUCCEEDED` after the tests
and the built executable's own self-test have passed.

## Requirements

* Windows 10 or 11, 64-bit.
* **Python 3.12, 64-bit**, from <https://www.python.org/downloads/windows/> (the "Windows installer (64-bit)").
  During installation tick *Add python.exe to PATH*; the `py` launcher is installed by default.
* Internet access for the first build (pip downloads the pinned wheels listed in `requirements-lock.txt`,
  about 240 MB). If you are behind a corporate proxy, set `HTTPS_PROXY` first.
* About 2 GB of free disk space.

No administrator rights are needed: everything installs into `.venv-build` inside the project folder.

## Steps

1. Copy the whole `aurelia-finance-lab` folder to the Windows PC (for example `C:\Work\aurelia-finance-lab`).
2. Open the folder in File Explorer and double-click **`build_windows.bat`**, or from a Command Prompt:

   ```
   cd C:\Work\aurelia-finance-lab
   build_windows.bat
   ```

   If several Python versions are installed and the script picks the wrong one:

   ```
   build_windows.bat -Python C:\Users\<you>\AppData\Local\Programs\Python\Python312\python.exe
   ```

3. The script runs these stages and prints each one:
   1. finds a 64-bit Python 3.12 (refuses any other version, because the dependencies are pinned for 3.12);
   2. creates `.venv-build` and installs `requirements-lock.txt` (binary wheels only);
   3. runs the test suite off-screen (`build\test-output.txt`, `build\test-results.xml`);
   4. runs PyInstaller with `packaging\aurelia.spec` (one-folder build, no console window, icon and version
      resource);
   5. starts the built `Aurelia_Finance_Lab.exe --selftest --quiet` against a temporary data folder and checks the
      report says `Overall: PASSED` (`build\exe-selftest-report.txt`);
   6. zips the folder to `dist\Aurelia_Finance_Lab-1.0.0-win64.zip`, writes `dist\SHA256SUMS.txt` and
      `build\BUILD_RESULT.txt`.

4. Start the app: `dist\Aurelia_Finance_Lab\Aurelia_Finance_Lab.exe`. To give it to someone else, send the zip; they
   unzip it anywhere and run the exe (no installation, no Python needed).

## Manual equivalent

If you prefer to run the commands yourself (PowerShell, in the project folder):

```
py -3.12 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-lock.txt
$env:QT_QPA_PLATFORM = "offscreen"; .\.venv-build\Scripts\python.exe -m pytest -q; Remove-Item Env:\QT_QPA_PLATFORM
.\.venv-build\Scripts\python.exe -m PyInstaller --clean --noconfirm packaging\aurelia.spec
Start-Process dist\Aurelia_Finance_Lab\Aurelia_Finance_Lab.exe -ArgumentList "--selftest","--quiet","--report","build\exe-selftest-report.txt" -Wait
Get-Content build\exe-selftest-report.txt
```

## Checking the result on another PC

Run `Aurelia_Finance_Lab.exe --selftest` (without `--quiet`): a dialog shows PASSED or FAILED and the path of the
report in `%APPDATA%\AureliaFinanceLab\diagnostics\`. All checks use temporary copies; the user's data is only read.

## Notes

* **Windows SmartScreen / antivirus.** A new unsigned executable may trigger "Windows protected your PC". Choose
  *More info → Run anyway*, or sign the executable with your organisation's code-signing certificate
  (`signtool sign /fd SHA256 /a dist\Aurelia_Finance_Lab\Aurelia_Finance_Lab.exe`). The one-folder build is used
  because one-file executables unpack to a temp folder at every start and trigger more false positives.
* **Size.** The folder is roughly 250–300 MB, mostly Qt and NumPy/pandas libraries.
* **Updating the version.** Change `__version__` in `aurelia/__init__.py` and the numbers in
  `packaging/version_info.txt`.
* **Regenerating the lock file** (only when changing dependencies): edit `requirements.txt` /
  `requirements-dev.txt`, then on Windows with Python 3.12: `pip install -r requirements-dev.txt` and
  `pip freeze > requirements-lock.txt`.
