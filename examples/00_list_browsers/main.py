"""List the Chromium-family browsers chauffeur can drive.

    uv run examples/00_list_browsers/main.py
"""

from chauffeur import installed_browsers


def main() -> None:
    browsers = installed_browsers()
    if not browsers:
        print("no supported browser installed")
        return
    for browser in browsers:
        print(f"{browser.id:10} {browser.name:18} {browser.binary}")


if __name__ == "__main__":
    main()
