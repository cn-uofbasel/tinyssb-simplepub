#

# tinyssb/wal.py
# 2022-04-24 <christian.tschudin@unibas.ch>

import os

class WAL:

    def __init__(self):
        self.apps = {}
        self.wal = None

    def playback(self, fn):
        # will execute each line of the WAL (if existing and END marker found)
        # After having replayed: removes the WAL and starts a new one
        if os.path.exists(fn):
            with open(fn,'r') as f:
                lines = f.read().split('\n')
            if len(lines) > 0 and lines[-1] == '':
                lines = lines[:-1]
            # print("playback - WAL content:")
            # [print(" ", l) for l in lines]
            if len(lines) > 0 and lines[-1] == 'ok':
                for cmd in lines:
                    cmd = cmd.split(' ')
                    if cmd[0] == 'ok': # end marker
                        break
                    if not cmd[0] in self.apps:
                        print("unknown app:", ' '.join(cmd))
                        continue
                    # ?? should cb return False if there is an error?
                    # ?? resulting in an abort of the complete playback?
                    self.apps[cmd[0]](cmd[1:])
            os.unlink(fn)
        else:
            print("no such file", fn)
        # success! Either no wal, no complete wal, or all commands executed.
        # Now create an empty wal for the next round
        self.wal = open(fn, 'w')

    def append(self, line=None):
        # adds the line, or closes the WAL if line==None (add a END marker)
        # after closing you must call playback() to execute the cmds
        assert self.wal != None
        if line == None:
            self.wal.write('ok\n')
            self.wal.close()
            self.wal = None
        else:
            self.wal.write(line + '\n')
            # self.wal.flush()

    def register_app(self, app_str, cb=None):
        # when replaying, a line starting with app_str will be called at cb
        # and the spac-separated args are passed as a list
        if cb == None:
            if app_str in self.apps:
                del self.apps[app_str]
            return
        self.apps[app_str] = cb

# eof
