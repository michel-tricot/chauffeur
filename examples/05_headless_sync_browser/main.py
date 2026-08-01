"""The synchronous API — same capabilities, no async/await.

SyncBrowser runs the async core on a background thread and blocks on each
call. Registered @command handlers run on that loop thread. This is the sync
twin of 02_headless_bidirectional.

    uv run examples/05_headless_sync_browser/main.py
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from chauffeur import LaunchSpec, SyncBrowser


def main() -> None:
    with TemporaryDirectory() as tmp:
        browser = SyncBrowser(LaunchSpec(profile=Path(tmp) / "profile", headless=True))

        @browser.command()
        def add(params: dict) -> dict:
            return {"sum": params["a"] + params["b"]}

        with browser:
            # Plain blocking calls — no await anywhere.
            print("user agent:", browser.evaluate("navigator.userAgent"))
            print("2 + 2 =", browser.evaluate("2 + 2"))

            # Browser -> Python: the page calls the registered command.
            print("page got:", browser.evaluate("py.call('add', {a: 20, b: 22})"))

            # Python -> browser: call a py.on handler the page registered.
            browser.evaluate("py.on('shout', async ({text}) => text.toUpperCase())")
            print("browser said:", browser.call("shout", {"text": "hi from sync python"}))


if __name__ == "__main__":
    main()
