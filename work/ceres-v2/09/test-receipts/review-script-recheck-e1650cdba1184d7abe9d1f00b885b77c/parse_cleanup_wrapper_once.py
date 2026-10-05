import ast
import hashlib
import sys
from pathlib import Path

source = Path(sys.argv[1])
raw = source.read_bytes()
ast.parse(raw.decode("utf-8-sig"), filename=str(source))
print("AST_OK " + source.name + " SHA256=" + hashlib.sha256(raw).hexdigest().upper())
