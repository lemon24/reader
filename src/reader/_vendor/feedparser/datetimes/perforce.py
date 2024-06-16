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

import email.utils
import re
import time


# for coverage test
branch_coverage = {
    "parse_data_nate_1": False,
    "parse_data_nate_2": False,
    "parse_data_nate_3": False,
    "parse_data_nate_4": False
}

def print_coverage():
    for branch, hit in branch_coverage.items():
        print(f"{branch} was {'hit' if hit else 'not hit'}")
    print("\n")


def _parse_date_perforce(date_string):
    """parse a date in yyyy/mm/dd hh:mm:ss TTT format"""
    # Fri, 2006/09/15 08:19:53 EDT
    _my_date_pattern = re.compile(r'(\w{,3}), (\d{,4})/(\d{,2})/(\d{2}) (\d{,2}):(\d{2}):(\d{2}) (\w{,3})')

    m = _my_date_pattern.search(date_string)
    if m is None:
        branch_coverage['parse_data_nate_1'] = True
        return None
    
    branch_coverage['parse_data_nate_2'] = True
    dow, year, month, day, hour, minute, second, tz = m.groups()
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    new_date_string = "%s, %s %s %s %s:%s:%s %s" % (dow, day, months[int(month) - 1], year, hour, minute, second, tz)
    tm = email.utils.parsedate_tz(new_date_string)

    if tm:
        branch_coverage['parse_data_nate_3'] = True
        return time.gmtime(email.utils.mktime_tz(tm))
    
    branch_coverage['parse_data_nate_4'] = True
    


# if __name__ == '__main__':
#     print("...Staring the parse_date_perforce TEST...")

#     # proper date in yyyy/mm/dd hh:mm:ss TTT format
#     result = _parse_date_perforce("Fri, 2006/09/15 08:19:53 EDT")
#     print(result)
#     print_coverage()


#     # proper Korean onblog format
#     result = _parse_date_perforce("2023년 06월 11일 09:15:00")
#     print(result)
#     print_coverage()
