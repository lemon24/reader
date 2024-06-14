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

from reader._vendor.feedparser.datetimes.rfc822 import _parse_date_rfc822


branch_coverage = { 
    "parse_date_asctime_1": False, 
    "parse_date_asctime_2": False,
    "parse_date_asctime_3": False,
    "parse_date_asctime_4": False
} 

_months = [
    'jan',
    'feb',
    'mar',
    'apr',
    'may',
    'jun',
    'jul',
    'aug',
    'sep',
    'oct',
    'nov',
    'dec',
]


def _parse_date_asctime(dt):
    """Parse asctime-style dates.

    Converts asctime to RFC822-compatible dates and uses the RFC822 parser
    to do the actual parsing.

    Supported formats (format is standardized to the first one listed):

    * {weekday name} {month name} dd hh:mm:ss {+-tz} yyyy
    * {weekday name} {month name} dd hh:mm:ss yyyy
    """

    parts = dt.split()

    # Insert a GMT timezone, if needed.
    if len(parts) == 5:
        branch_coverage["parse_date_asctime_1"] = True
        parts.insert(4, '+0000')
    else:
        branch_coverage["parse_date_asctime_2"] = True

    # Exit if there are not six parts.
    if len(parts) != 6:
        branch_coverage["parse_date_asctime_3"] = True
        return None
    else:
        branch_coverage["parse_date_asctime_4"] = True

    # Reassemble the parts in an RFC822-compatible order and parse them.
    return _parse_date_rfc822(' '.join([
        parts[0], parts[2], parts[1], parts[5], parts[3], parts[4],
    ]))

def branch_coverage_print_asctime(): 
    hitItems = 0
    for branch, hit in branch_coverage.items(): 
        if hit:
            hitItems = hitItems + 1
            print(branch + " was hit")
        else:
            print(branch + " was not hit")
    print("Branch coverage percentage: " + str((hitItems/4) * 100) + "%")

if __name__ == '__main__':
    _parse_date_asctime("INVALID")
    branch_coverage_print_asctime()

    _parse_date_asctime("thursday may 13 18:55:30 2024")
    branch_coverage_print_asctime()
