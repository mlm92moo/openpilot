"""Bounded JSONL diagnostic output with explicit termination records."""
import json


class OutputLimit(Exception):
  pass


class JsonWriter:
  FOOTER_RESERVE = 65_536

  def __init__(self, path, max_bytes):
    if max_bytes < 2 * self.FOOTER_RESERVE:
      raise ValueError("output budget too small")
    self.file = open(path, "xb")
    self.max_bytes = max_bytes
    self.bytes_written = 0

  def write(self, record, final=False):
    data = (json.dumps(record, allow_nan=False, separators=(",", ":")) + "\n").encode()
    limit = self.max_bytes if final else self.max_bytes - self.FOOTER_RESERVE
    if self.bytes_written + len(data) > limit:
      raise OutputLimit("diagnostic output budget reached")
    self.file.write(data)
    self.bytes_written += len(data)
    if record.get("type") in {"status", "end"}:
      self.file.flush()

  def close(self):
    self.file.close()
