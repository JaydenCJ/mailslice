"""mailslice — stream-split giant Google Takeout mbox files.

Public API surface. The typical library flow mirrors the CLI:

    from mailslice import MboxReader, Router, RouteConfig, open_mbox, split

    with open_mbox("takeout.mbox") as fp:
        report = split(
            MboxReader(fp),
            out_dir="mail",
            fmt="maildir",
            router=Router(RouteConfig()),
        )
    print(report.render())

Everything runs offline, in constant memory, with zero dependencies beyond
the Python standard library.
"""

from .errors import BodyConsumedError, MailsliceError, NotAnMboxError
from .headers import (
    HeaderBlock,
    decode_mime_words,
    message_date,
    message_year,
    parse_from_line_date,
)
from .labels import (
    UNLABELED,
    folder_labels,
    gmail_labels,
    is_flag_label,
    is_system_label,
    label_to_path,
    maildir_flags,
    parse_label_header,
    primary_label,
    sanitize_segment,
)
from .mboxstream import (
    ESCAPING_MODES,
    MboxMessage,
    MboxReader,
    is_from_line,
    iter_lines,
    open_mbox,
    unstuff,
)
from .report import SplitReport, human_size
from .router import GROUP_CHOICES, NO_DATE, RouteConfig, RouteResult, Router
from .splitter import FORMATS, scan, split
from .writers import EmlWriter, MaildirWriter, slugify

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # errors
    "MailsliceError", "NotAnMboxError", "BodyConsumedError",
    # headers
    "HeaderBlock", "decode_mime_words", "message_date", "message_year",
    "parse_from_line_date",
    # labels
    "UNLABELED", "parse_label_header", "gmail_labels", "is_flag_label",
    "is_system_label", "folder_labels", "primary_label", "maildir_flags",
    "sanitize_segment", "label_to_path",
    # mbox streaming
    "ESCAPING_MODES", "MboxMessage", "MboxReader", "is_from_line",
    "iter_lines", "open_mbox", "unstuff",
    # routing
    "GROUP_CHOICES", "NO_DATE", "RouteConfig", "RouteResult", "Router",
    # writing & orchestration
    "MaildirWriter", "EmlWriter", "slugify", "FORMATS", "scan", "split",
    # reporting
    "SplitReport", "human_size",
]
