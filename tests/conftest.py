# SPDX-License-Identifier: MIT
# Copyright (c) 2026 LouisZhou

# tests/conftest.py
import pathlib

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture(name):
    return FIXTURES / name
