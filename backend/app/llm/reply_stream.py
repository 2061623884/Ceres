"""Minimal incremental extraction of the proposal ``reply`` string from JSON tokens.

Only targets the current semantic contract field ``reply``. This is not a JSON
parser: the assembled body must still pass ``extract_json_object`` before use.
"""

from __future__ import annotations


class ReplyStreamExtractor:
    """Decode newly available ``reply`` text from a growing JSON body."""

    _SEARCH = "SEARCH"
    _IN_STRING = "IN_STRING"

    def __init__(self) -> None:
        self._raw = ""
        self._phase = self._SEARCH
        self._decoded: list[str] = []
        self._escape: str | None = None
        self._unicode_digits = ""
        self._scan_pos = 0

    @property
    def emitted_text(self) -> str:
        return "".join(self._decoded)

    def feed(self, chunk: str) -> str:
        if not chunk or self._phase == "DONE":
            return ""
        self._raw += chunk
        newly: list[str] = []
        while self._scan_pos < len(self._raw):
            ch = self._raw[self._scan_pos]
            if self._phase == self._SEARCH:
                if self._raw.startswith('"reply"', self._scan_pos):
                    self._scan_pos += len('"reply"')
                    self._phase = "AFTER_KEY"
                    continue
                self._scan_pos += 1
                continue
            if self._phase == "AFTER_KEY":
                if ch.isspace():
                    self._scan_pos += 1
                    continue
                if ch != ":":
                    self._scan_pos += 1
                    self._phase = self._SEARCH
                    continue
                self._scan_pos += 1
                self._phase = "BEFORE_STRING"
                continue
            if self._phase == "BEFORE_STRING":
                if ch.isspace():
                    self._scan_pos += 1
                    continue
                if ch != '"':
                    self._scan_pos += 1
                    self._phase = self._SEARCH
                    continue
                self._scan_pos += 1
                self._phase = self._IN_STRING
                continue
            if self._phase == self._IN_STRING:
                if self._escape == "u":
                    if ch in "0123456789abcdefABCDEF":
                        self._unicode_digits += ch
                        self._scan_pos += 1
                        if len(self._unicode_digits) == 4:
                            newly.append(chr(int(self._unicode_digits, 16)))
                            self._escape = None
                            self._unicode_digits = ""
                        continue
                    self._escape = None
                    self._unicode_digits = ""
                    continue
                if self._escape is not None:
                    mapping = {'"': '"', "\\": "\\", "/": "/", "n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}
                    if self._escape == "" and ch in mapping:
                        newly.append(mapping[ch])
                        self._escape = None
                        self._scan_pos += 1
                        continue
                    if self._escape == "" and ch == "u":
                        self._escape = "u"
                        self._scan_pos += 1
                        continue
                    self._escape = None
                    continue
                if ch == "\\":
                    self._escape = ""
                    self._scan_pos += 1
                    continue
                if ch == '"':
                    self._phase = "DONE"
                    self._scan_pos += 1
                    break
                newly.append(ch)
                self._scan_pos += 1
                continue
            break
        if newly:
            self._decoded.extend(newly)
            return "".join(newly)
        return ""


__all__ = ["ReplyStreamExtractor"]
