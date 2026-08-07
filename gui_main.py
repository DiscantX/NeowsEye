"""
gui_main.py

GUI entry point for Coaching Mode.

Tkinter's CoachOverlay.mainloop() must run on the main thread, for the
life of the process -- that's what pumps the .after() callbacks
CoachOverlay/UIObserver rely on for thread-safe widget updates.

main.main() also blocks its calling thread for the life of the run
(StreamClient.start(), then a `while True: client.get_message()`
loop). Two things that each want to own the main thread forever can't
share one, so main.main() runs on a background daemon thread here, and
mainloop() owns the main thread instead. This is the only difference
from the terminal path -- main.main()'s own logic doesn't change.

Shutdown: closing the overlay window is treated as "quit Neow's Eye"
(not "hide the GUI, keep coaching in the background") -- see
CoachOverlay._on_close. The on_close callback below closes the
StreamClient socket, which main()'s poll loop already knows how to
treat as "adapter disconnected" and exits on its own via its existing
code path. No new shutdown/timeout logic needed on main()'s side.
"""

import threading

from coaching_observer import ObserverBroadcaster
from main import main as run_coaching_loop
from terminal_observer import TerminalObserver
from tkinter_app import CoachOverlay
from ui_observer import UIObserver


def main():
    # main() hands us the StreamClient once it's connected (via
    # on_client_ready), and _on_close needs it to trigger shutdown --
    # this dict is just a mutable box the two closures below can share.
    client_holder = {}
    tracker_holder = {}

    def handle_close():
        client = client_holder.get("client")
        if client:
            client.close()
    
    def handle_reset_rule_change(tz_name):
        tracker = tracker_holder.get("tracker")
        if tracker:
            tracker.set_reset_rule(tz_name, 0)
        # else: user clicked before the tracker was ready (e.g. still
        # waiting on the CommunicationMod connection) -- the button's
        # own label already updated, and set_reset_rule() will apply
        # once the run actually starts, so silently no-op is fine here.

    overlay = CoachOverlay(on_close=handle_close, on_reset_rule_change=handle_reset_rule_change)
    
    # Terminal output is kept alongside the GUI -- useful for anyone
    # running this from a console for extra visibility/debugging,
    # and it's what already prints connection-lost/error messages.
    observer = ObserverBroadcaster([TerminalObserver(), UIObserver(overlay)])

    worker_thread = threading.Thread(
        target=run_coaching_loop,
        args=(observer,),
        kwargs={
            "on_client_ready": lambda c: client_holder.update(client=c),
            "on_usage_tracker_ready": lambda t: tracker_holder.update(tracker=t),
        },
        daemon=True,
    )
    worker_thread.start()

    overlay.mainloop()


if __name__ == "__main__":
    main()