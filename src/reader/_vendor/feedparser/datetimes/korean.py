# Copyright 2010-2021 Kurt McKee <contactme@kurtmckee.org>
# Copyright 2002-2008 Mark Pilgrim
# All rights reserved.
#
# This file is a part of feedparser.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS 'AS IS'
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import re

from reader._vendor.feedparser.datetimes.w3dtf import _parse_date_w3dtf

# 8-bit date handling routines written by ytrewq1.
_korean_year = '\ub144' # b3e2 in euc-kr
_korean_month = '\uc6d4' # bff9 in euc-kr
_korean_day = '\uc77c' # c0cf in euc-kr
_korean_am = '\uc624\uc804' # bfc0 c0fc in euc-kr
_korean_pm = '\uc624\ud6c4' # bfc0 c8c4 in euc-kr

_korean_onblog_date_re = re.compile(
    r'(\d{4})%s\s+(\d{2})%s\s+(\d{2})%s\s+(\d{2}):(\d{2}):(\d{2})'
    % (_korean_year, _korean_month, _korean_day)
)

_korean_nate_date_re = re.compile(
    r'(\d{4})-(\d{2})-(\d{2})\s+(%s|%s)\s+(\d{,2}):(\d{,2}):(\d{,2})'
    % (_korean_am, _korean_pm))


def _parse_date_onblog(dateString):
    """Parse a string according to the OnBlog 8-bit date format"""
    m = _korean_onblog_date_re.match(dateString)
    if not m:
        return
    w3dtfdate = '%(year)s-%(month)s-%(day)sT%(hour)s:%(minute)s:%(second)s%(zonediff)s' % \
                {'year': m.group(1), 'month': m.group(2), 'day': m.group(3),
                 'hour': m.group(4), 'minute': m.group(5), 'second': m.group(6),
                 'zonediff': '+09:00'}
    return _parse_date_w3dtf(w3dtfdate)


# for coverage test
branch_coverage = {
    "parse_data_nate_1": False,
    "parse_data_nate_2": False,
    "parse_data_nate_3": False,
    "parse_data_nate_4": False,
    "parse_data_nate_5": False,
    "parse_data_nate_6": False
}

def print_coverage():
    for branch, hit in branch_coverage.items():
        print(f"{branch} was {'hit' if hit else 'not hit'}")
    print("\n")



def _parse_date_nate(dateString):
    """Parse a string according to the Nate 8-bit date format"""
    print(f"Input DateString: {dateString}")

    m = _korean_nate_date_re.match(dateString)
    if not m:
        branch_coverage["parse_data_nate_1"] = True
        return
    
    branch_coverage["parse_data_nate_2"] = True
    hour = int(m.group(5))
    ampm = m.group(4)

    if ampm == _korean_pm:
        branch_coverage["parse_data_nate_3"] = True
        hour += 12

    branch_coverage["parse_data_nate_4"] = True

    hour = str(hour)
    if len(hour) == 1:
        branch_coverage["parse_data_nate_5"] = True
        hour = '0' + hour
    
    branch_coverage["parse_data_nate_6"] = True

    w3dtfdate = '%(year)s-%(month)s-%(day)sT%(hour)s:%(minute)s:%(second)s%(zonediff)s' % \
                {
                    'year': m.group(1),
                    'month': m.group(2),
                    'day': m.group(3),
                    'hour': hour,
                    'minute': m.group(6),
                    'second': m.group(7),
                    'zonediff': '+09:00',
                }
    return _parse_date_w3dtf(w3dtfdate)

def return_w3dtf(m):
    w3dtfdate = '%(year)s-%(month)s-%(day)sT%(hour)s:%(minute)s:%(second)s%(zonediff)s' % {
        'year': m.tm_year,
        'month': m.tm_mon,
        'day': m.tm_mday,
        'hour': m.tm_hour,
        'minute': m.tm_min,
        'second': m.tm_sec,
        'zonediff': '+09:00',
    }
    return w3dtfdate


# if __name__ == '__main__':
#     w3dtf_regex = re.compile(r'^\d{4}-\d{1,2}-\d{1,2}T\d{1,2}:\d{1,2}:\d{1,2}([+-]\d{2}:\d{2}|Z)$')
    
#     print("...Staring the _parse_date_nate TEST...")

#     # proper Korean nate format
#     result = _parse_date_nate("2023-06-11 오전 09:15:00")
#     #print(return_w3dtf(result))
#     print_coverage()
#     result = _parse_date_nate("2021-06-15 오후 14:45:30")
#     print_coverage()

#     # proper Korean onblog format
#     result = _parse_date_nate("2023년 06월 11일 09:15:00")
#     print_coverage()
#     result = _parse_date_nate("2021년 06월 15일 14:45:30")
#     print_coverage()

#     # different country format (Greek && Japan)
#     result = _parse_date_nate("11/06/2023 15:30:45")
#     print_coverage()
#     result = _parse_date_nate("2023年06月11日 15時30分45秒")
#     print_coverage()

#     # Korean nate country format but written wrong
#     result = _parse_date_nate("2023-6-011 전 009:15:00")
#     print_coverage()
#     result = _parse_date_nate("2021/06/15 14:45:30")
#     print_coverage()

#     # completely different format
#     result = _parse_date_nate("Hello I'm Edwin")
#     print_coverage()
#     result = _parse_date_nate("")
#     print_coverage()
