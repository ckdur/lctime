# Copyright (c) 2019-2020 Thomas Kramer.
# SPDX-FileCopyrightText: 2022 Thomas Kramer <code@tkramer.ch>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Helpers related to licencing.
"""


def original_source_repository() -> str:
    return "https://codeberg.org/librecell/lctime"


def licence_notice_string_single_line() -> str:
    return "This program is licenced under the AGPL-3.0-or-later licence. Source code:  {}".format(
        original_source_repository())
