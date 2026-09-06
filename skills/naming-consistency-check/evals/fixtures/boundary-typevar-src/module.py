# Minimal reproduction of a false positive found dogfooding this skill
# on psf/requests (src/requests/_types.py: `_T_co = TypeVar("_T_co",
# covariant=True)`) — PEP 484's own TypeVar naming convention is not
# this tree's general variable-naming convention.
import typing

first_value = make_first()
second_value = make_second()
third_value = make_third()

_T_co = typing.TypeVar("_T_co", covariant=True)
