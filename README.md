# Commercial Splitter

Windows desktop application for detecting, reviewing, and exporting commercial clips from recordings.

**Copyright © 2026 Longthony — MIT licensed.**

## Run from source

Install Python 3.11+, then `pip install -r requirements.txt` and `python src/Commercial_Splitter.py`.

Install FFmpeg and FFprobe on PATH, or place the executables in the same folder as the source. `ffplay.exe` is useful for some previews.

## Build on Windows

Double-click `scripts/build.bat` from the repository checkout. Output is in `dist/Commercial Splitter.exe`.

## Updates

Version 4.9.0 introduces **Help → Check for Updates**. It checks the latest published GitHub Release and can open the official release page. **It does not download, install, or silently replace software.** A secure automatic installer is planned for a later release.

## Privacy

Recordings and project data remain local. The update checker contacts GitHub only when manually invoked. Do not commit personal recordings, `.csproj` projects, or recovery files.

## License

MIT. See [LICENSE](LICENSE).
