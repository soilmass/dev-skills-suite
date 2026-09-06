"""Planted fixture: a 'long' file. The eval passes --long-file-lines 40
so this 60-line module trips debt/long-file without shipping a
500-line fixture."""


def op_01(x):
    return x + 1


def op_02(x):
    return x + 2


def op_03(x):
    return x + 3


def op_04(x):
    return x + 4


def op_05(x):
    return x + 5


def op_06(x):
    return x + 6


def op_07(x):
    return x + 7


def op_08(x):
    return x + 8


def op_09(x):
    return x + 9


def op_10(x):
    return x + 10


def op_11(x):
    return x + 11


def op_12(x):
    return x + 12


def op_13(x):
    return x + 13


def op_14(x):
    return x + 14


def dispatch(n, x):
    return globals()[f"op_{n:02d}"](x)
