import re
import subprocess
from functools import cache

from ....exceptions import EngineError


###########################################################################################################
###########################################################################################################
@cache
def encoders_of(binary: str) -> frozenset[str]:
    listing = subprocess.run([binary, "-hide_banner", "-encoders"], capture_output=True, text=True, check=True).stdout
    names = set()
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0][0] in "VA" and parts[1] != "=":
            names.add(parts[1])
    return frozenset(names)


###########################################################################################################
###########################################################################################################
@cache
def codec_encoders(binary: str) -> dict[str, list[str]]:
    listing = subprocess.run([binary, "-hide_banner", "-codecs"], capture_output=True, text=True, check=True).stdout
    table: dict[str, list[str]] = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][1] == "E" and parts[1] != "=":
            names = re.search(r"\(encoders: ([^)]+)\)", line)
            table[parts[1]] = names.group(1).split() if names else [parts[1]]
    return table


###########################################################################################################
###########################################################################################################
def pick_encoder(binary: str, names: list[str]) -> str:
    available = encoders_of(binary)
    for name in names:
        if name in available:
            return name
        for candidate in codec_encoders(binary).get(name, []):
            if candidate in available:
                return candidate
    raise EngineError(f"none of the encoders {names} exist in {binary}")
