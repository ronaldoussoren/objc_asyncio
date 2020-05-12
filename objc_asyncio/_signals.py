import signal
import sys
import typing


class SignalMixin:
    def __init__(self):
        self._signal_handlers = {}

    def add_signal_handler(
        self, sig: int, callback: typing.Callable[..., typing.Any], *args: typing.Any
    ):
        """Add a handler for a signal.  UNIX only.

        Raise ValueError if the signal number is invalid or uncatchable.
        Raise RuntimeError if there is a problem setting up the handler.
        """
        raise NotImplementedError(24)

    def remove_signal_handler(self, sig: int):
        """Remove a handler for a signal.  UNIX only.

        Return True if a signal handler was removed, False if not.
        """
        raise NotImplementedError(25)

    if sys.version_info[:2] >= (3, 8):

        def _check_signal(self, sig: int):
            """Internal helper to validate a signal.

            Raise ValueError if the signal number is invalid or uncatchable.
            Raise RuntimeError if there is a problem setting up the handler.
            """
            if not isinstance(sig, int):
                raise TypeError(f"sig must be an int, not {sig!r}")

            if sig not in signal.valid_signals():
                raise ValueError(f"invalid signal number {sig}")

    else:

        def _check_signal(self, sig: int):
            """Internal helper to validate a signal.

            Raise ValueError if the signal number is invalid or uncatchable.
            Raise RuntimeError if there is a problem setting up the handler.
            """
            if not isinstance(sig, int):
                raise TypeError(f"sig must be an int, not {sig!r}")

            if not (1 <= sig < signal.NSIG):
                raise ValueError(f"sig {sig} out of range(1, {signal.NSIG})")
