"""Exception hierarchy for mailslice.

Everything mailslice raises deliberately derives from :class:`MailsliceError`
so callers embedding the library can catch one type at the boundary while the
CLI maps each subclass to a clear, non-traceback error message.
"""

from __future__ import annotations

__all__ = ["MailsliceError", "NotAnMboxError", "BodyConsumedError"]


class MailsliceError(Exception):
    """Base class for all errors raised by mailslice."""


class NotAnMboxError(MailsliceError):
    """The input does not start with a valid mbox ``From `` separator line.

    Raised on the first message read, before anything is written, so a user
    who points mailslice at the wrong Takeout file (the JSON sidecar, a zip,
    an HTML export) fails fast instead of producing an empty split.
    """


class BodyConsumedError(MailsliceError):
    """A message body iterator was requested twice.

    Bodies are streamed straight off the input file and are therefore
    single-shot; a second iteration would silently yield nothing, which is
    far worse than an explicit error.
    """
