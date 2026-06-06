from __future__ import annotations


class Secret:
    """Wrapper opaque pour une valeur secrète.

    La valeur réelle n'est accessible que via .reveal(). __repr__ et __str__
    retournent "***" pour prévenir toute fuite accidentelle dans les logs.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(***)"

    def __str__(self) -> str:
        return "***"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Secret):
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)
