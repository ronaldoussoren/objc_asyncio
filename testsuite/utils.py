import signal

from functool import wraps


def timed_function(delay):
    """
    Abort the current process when de decorated function doesn't
    return within *delay* seconds.
    """
    # NOTE: This does not set a signal handler for SIGALRM because
    # this is used to abort code that might block inside Cocoa
    # APIs.
    def decorator(function):
        @wraps(function)
        def around(*args, **kwds):
            signal.alarm(delay)
            try:
                return function(*args, **kwds)
            finally:
                signal.alarm(0)

        return around

    return decorator
