#

# tinyssb/dbg.py
# 2022-04-06 <christian.tschudin@unibas.ch>

import sys
import time

def get_ms():
    if sys.platform == 'LoPy4':
        return str(time.ticks_ms() + 1000)[-3:]
    return str(time.time()).split('.')[1][:3]

TERM_GREEN    = "\x1b[92m"
TERM_GRAY     = "\x1b[37m"
TERM_MAGENTA  = "\x1b[95m"
TERM_RED      = "\x1b[91m"
TERM_BLUE     = "\x1b[94m"
TERM_YELLOW   = "\x1b[93m"
TERM_NORM     = "\x1b[0m"
TERM_ERROR    = "\x1b[42m"

GRE,GRA,MAG,RED,BLU,YEL,ERR = (TERM_GREEN, TERM_GRAY, TERM_MAGENTA,
                               TERM_RED, TERM_BLUE, TERM_YELLOW, TERM_ERROR)

dbg_logfile = None
dbg_screen_output_enabled = True
    
def tofile(path):
    global dbg_logfile
    dbg_logfile = open(path, "a")

def dbg(col, *args):
    global dbg_logfile, dbg_screen_output_enabled
    # t = time.time()
    # print(time.strftime('%H:%M:%S.') + str(t).split('.')[1][:3] + ' ', end='')
    t = time.localtime()
    tstr = ('%02d:%02d:%02d.' % t[3:6]) + get_ms()
    astr = ' '.join([str(a) for a in args])
    if dbg_logfile:
        dbg_logfile.write(tstr, astr)
        dbg_logfile.flush()
    if dbg_screen_output_enabled:
        print(tstr, col, astr + TERM_NORM)
