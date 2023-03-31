# Copyright (c) 2019-2020 Thomas Kramer.
# SPDX-FileCopyrightText: 2022 Thomas Kramer <code@tkramer.ch>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

name = "lctime"

import sys
import os

def trace_calls(frame, event, arg):
    if event != 'call':
        return
    co = frame.f_code
    func_name = co.co_name
    if func_name == 'write':
        # Ignore write() calls from print statements
        return
    func_line_no = frame.f_lineno
    func_filename = co.co_filename
    caller = frame.f_back
    if caller is None:
        print('Call to %s on line %s of %s from unknown' % \
          (func_name, func_line_no, func_filename))
    else:
        caller_line_no = caller.f_lineno
        caller_filename = caller.f_code.co_filename
        print('Call to %s on line %s of %s from line %s of %s' % \
          (func_name, func_line_no, func_filename,
          caller_line_no, caller_filename))
    return

if 'DEBUG_LCTIME' in os.environ:
    sys.settrace(trace_calls)
